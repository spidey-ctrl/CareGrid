"""CPU-trained gradient-boosted tree survival model plus its hold-out validation harness.

Ticket 08: replaces the deterministic fakes behind the ``SurvivalModel`` adapter with a
real gradient-boosted tree trained on the ICU Patient Outcome Prediction dataset (SOFA +
age + comorbidity; target survival to hospital discharge), evaluated on a fixed 20%
hold-out split, and gated so no demonstration can run on a model that fails the agreed
tolerance.

This module is the standalone validation harness — it never sits in the engine's runtime
path (spec: Implementation Decisions, "Validation harness"). The engine keeps depending
only on the ``SurvivalModel`` adapter; consumers pick up the trained model through
:func:`establish_survival_model`, which raises on a failed gate.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from .sofa import Sofa
from .survival import SurvivalPrediction

if TYPE_CHECKING:
    from xgboost import Booster

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
X_TRAIN_CSV = DATA_DIR / "X_train_2025.csv"
Y_TRAIN_CSV = DATA_DIR / "y_train_2025.csv"
MODELS_DIR = DATA_DIR / "models"

# The recorded split seed — reproducibility constant. Same dataset + same seed ⇒ same
# hold-out, same metrics, same verdict, run after run.
SPLIT_SEED = 20260818
TRAIN_FRACTION = 0.8

# Agreed validation tolerance (spec user story 50): discrimination and per-decile
# calibration sanity checks that gate any demonstration.
AUC_MIN = 0.70
CALIBRATION_TOLERANCE = 0.05

FEATURE_NAMES = ("sofa", "age", "comorbidity_count")

# The eICU-style dataset encodes a missing SOFA as -1; XGBoost treats NaN natively.
NA_VALUE = "-1"

# Fixed model hyper-parameters, kept in one place so the report can cite what was trained.
# A shallow, warm-paced tree has the best calibration on this small ICU subset; deeper
# forests gain no AUC on the mandated feature set and overconcentrate their probabilities.
BOOSTER_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 3,
    "eta": 0.05,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "tree_method": "hist",
    "n_jobs": 1,  # single-threaded so training is bit-for-bit reproducible
    "seed": SPLIT_SEED,
}
N_BOOST_ROUNDS = 250


@dataclass(frozen=True)
class CalibrationBin:
    """One equal-count bin of the hold-out, ranked by predicted survival."""

    index: int
    count: int
    predicted: float
    observed: float
    diff: float


@dataclass(frozen=True)
class ValidationReport:
    """The recorded outcome of one hold-out validation run."""

    seed: int
    n_train: int
    n_test: int
    auc: float
    brier: float
    calibration: tuple[CalibrationBin, ...]

    def passed(self) -> bool:
        """The gate: AUC ≥ 0.7 and every decile within ±5% of its observed rate."""
        if self.auc < AUC_MIN:
            return False
        return all(bin_.diff <= CALIBRATION_TOLERANCE for bin_ in self.calibration)

    def _gate_reasons(self) -> list[str]:
        reasons = []
        if self.auc < AUC_MIN:
            reasons.append(f"AUC-ROC {self.auc:.3f} < {AUC_MIN:.2f}")
        for bin_ in self.calibration:
            if bin_.diff > CALIBRATION_TOLERANCE:
                reasons.append(
                    f"decile {bin_.index} off by {bin_.diff:.3f} "
                    f"(allowed ≤ {CALIBRATION_TOLERANCE:.2f})"
                )
        return reasons

    def describe(self) -> str:
        """The human-readable report printed by the harness and on a failed gate."""
        lines = [
            "Survival model validation report",
            f"  split seed ................ {self.seed}",
            f"  training rows ............. {self.n_train}",
            f"  hold-out rows ............. {self.n_test}",
            f"  AUC-ROC ................... {self.auc:.3f}",
            f"  Brier score ............... {self.brier:.3f}",
            f"  gate: passed .............. ✓ (AUC ≥ {AUC_MIN:.2f})"
            if self.passed()
            else f"  gate: FAILED ............... (AUC ≥ {AUC_MIN:.2f}, "
            f"each decile within ±{CALIBRATION_TOLERANCE:.2f})",
            "  calibration per decile (predicted vs observed):",
        ]
        for bin_ in self.calibration:
            lines.append(
                f"      #{bin_.index:<2} n={bin_.count:<3} "
                f"predicted {bin_.predicted:.3f}  observed {bin_.observed:.3f}  "
                f"|diff| {bin_.diff:.3f}"
            )
        return "\n".join(lines)


class ModelValidationError(RuntimeError):
    """Raised when the trained model fails the validation gate — demonstrations blocked."""


def report_to_dict(report: ValidationReport) -> dict[str, object]:
    """Serialize the recorded report for the durable validation artifact."""
    return {
        "seed": report.seed,
        "n_train": report.n_train,
        "n_test": report.n_test,
        "auc": float(round(report.auc, 4)),
        "brier": float(round(report.brier, 4)),
        "passed": report.passed(),
        "calibration": [
            {
                "decile": bin_.index,
                "count": bin_.count,
                "predicted": float(round(bin_.predicted, 4)),
                "observed": float(round(bin_.observed, 4)),
                "diff": float(round(bin_.diff, 4)),
            }
            for bin_ in report.calibration
        ],
    }


# --------------------------------------------------------------------------------------
# Metric maths — pure functions so the report, the gate, and the tests stay hermetic and
# reproducible with no scientific stack beyond the booster itself.
# --------------------------------------------------------------------------------------


def roc_auc(y_true: Sequence[float], y_prob: Sequence[float]) -> float:
    """Area under the ROC curve by rank-sum (Mann-Whitney), ties averaged.

    Deterministic and dependency-free; 0.5 = no better than chance, 1.0 = perfect.
    """
    y_true = list(y_true)
    y_prob = list(y_prob)
    n = len(y_true)
    if n == 0:
        raise ValueError("roc_auc needs at least one sample")
    n_pos = sum(1 for y in y_true if y)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5

    order = sorted(range(n), key=lambda i: y_prob[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and y_prob[order[j]] == y_prob[order[i]]:
            j += 1
        average_rank = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[order[k]] = average_rank
        i = j

    rank_sum = sum(ranks[i] for i in range(n) if y_true[i])
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def brier_score(y_true: Sequence[float], y_prob: Sequence[float]) -> float:
    """Mean squared error between predicted probabilities and binary outcomes."""
    y_true = list(y_true)
    y_prob = list(y_prob)
    if not y_true:
        raise ValueError("brier_score needs at least one sample")
    return sum((p - y) ** 2 for p, y in zip(y_prob, y_true)) / len(y_true)


def decile_calibration(
    y_true: Sequence[float], y_prob: Sequence[float], bins: int = 10
) -> tuple[CalibrationBin, ...]:
    """Equal-count calibration bins ranked by predicted survival.

    Each bin holds its mean predicted probability and the observed outcome rate; the
    gate reads ``diff`` = |predicted − observed|, so a well-calibrated model keeps every
    decile within tolerance.
    """
    y_true = list(y_true)
    y_prob = list(y_prob)
    n = len(y_true)
    if n == 0:
        raise ValueError("decile_calibration needs at least one sample")
    order = sorted(range(n), key=lambda i: y_prob[i])
    size = (n + bins - 1) // bins
    result: list[CalibrationBin] = []
    for b in range(bins):
        chunk = order[b * size : (b + 1) * size]
        if not chunk:
            break
        preds = [y_prob[i] for i in chunk]
        truths = [y_true[i] for i in chunk]
        predicted = sum(preds) / len(preds)
        observed = sum(truths) / len(truths)
        result.append(
            CalibrationBin(
                index=b + 1,
                count=len(chunk),
                predicted=predicted,
                observed=observed,
                diff=abs(predicted - observed),
            )
        )
    return tuple(result)


def validation_report(
    *,
    seed: int,
    n_train: int,
    y_true: Sequence[float],
    y_prob: Sequence[float],
) -> ValidationReport:
    """Assemble the full recorded report from one hold-out prediction run."""
    return ValidationReport(
        seed=seed,
        n_train=n_train,
        n_test=len(y_true),
        auc=roc_auc(y_true, y_prob),
        brier=brier_score(y_true, y_prob),
        calibration=decile_calibration(y_true, y_prob),
    )


# --------------------------------------------------------------------------------------
# Dataset plumbing
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Row:
    sofa: float
    age: float
    comorbidity_count: int
    survival: float


def _normalise(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _float_or_nan(value: str) -> float:
    text = value.strip()
    if not text or text == NA_VALUE:
        return float("nan")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _load_rows(x_csv: Path, y_csv: Path) -> list[_Row]:
    with open(x_csv, newline="") as f:
        x_rows = list(csv.DictReader(f))
    with open(y_csv, newline="") as f:
        y_rows = list(csv.DictReader(f))
    if not x_rows or len(x_rows) != len(y_rows):
        raise ValueError(
            f"dataset size mismatch: {x_csv.name} has {len(x_rows)} rows, "
            f"{y_csv.name} has {len(y_rows)}"
        )

    x_headers = x_rows[0]
    y_headers = y_rows[0]
    sofa_col = next(
        (k for k in x_headers if _normalise(k) == "sofa"), None
    )
    age_col = next((k for k in x_headers if _normalise(k) == "age"), None)
    death_col = next(
        (k for k in y_headers if _normalise(k) in {"in_hospital_death", "inhospitaldeath"}),
        None,
    )
    if sofa_col is None or age_col is None:
        raise ValueError(
            f"{x_csv.name} must declare SOFA and Age columns "
            f"(found: {', '.join(x_headers[:8])}…)"
        )
    if death_col is None:
        raise ValueError(f"{y_csv.name} must declare an in-hospital death outcome column")

    rows: list[_Row] = []
    for x_row, y_row in zip(x_rows, y_rows):
        survival_text = y_row[death_col].strip()
        try:
            death = float(survival_text)
        except ValueError:
            continue
        if death not in (0.0, 1.0):
            continue
        survival = 1.0 - death
        rows.append(
            _Row(
                sofa=_float_or_nan(x_row[sofa_col]),
                age=_float_or_nan(x_row[age_col]),
                comorbidity_count=0,
                survival=survival,
            )
        )
    return rows


def _stratified_split(
    rows: Sequence[_Row], seed: int, fraction: float
) -> tuple[list[_Row], list[_Row]]:
    """Deterministic stratified split on survival, reproduceable from the seed."""
    rng = random.Random(seed)
    pos = [i for i, row in enumerate(rows) if row.survival == 1.0]
    neg = [i for i, row in enumerate(rows) if row.survival == 0.0]
    rng.shuffle(pos)
    rng.shuffle(neg)
    n_pos_train = int(round(len(pos) * fraction))
    n_neg_train = int(round(len(neg) * fraction))
    train_idx = set(pos[:n_pos_train] + neg[:n_neg_train])
    test_idx = [i for i in range(len(rows)) if i not in train_idx]
    return [rows[i] for i in sorted(train_idx)], [rows[i] for i in test_idx]


# --------------------------------------------------------------------------------------
# Training and the servable adapter
# --------------------------------------------------------------------------------------


def fit_booster(
    features: Sequence[Sequence[float]],
    survival_targets: Sequence[float],
    *,
    seed: int = SPLIT_SEED,
) -> Booster:
    """Train the CPU gradient-boosted tree; single-threaded for reproducibility."""
    import numpy as np
    import xgboost as xgb

    params = {**BOOSTER_PARAMS, "seed": seed}
    x_data = np.asarray(features, dtype=np.float64)
    y_data = np.asarray(survival_targets, dtype=np.float64)
    dtrain = xgb.DMatrix(x_data, label=y_data)
    return xgb.train(params, dtrain, num_boost_round=N_BOOST_ROUNDS)


class TrainedSurvivalModel:
    """The servable side of the harness: the booster behind the engine's adapter.

    SHAP attributions come straight from XGBoost's native tree contributions
    (``pred_contribs``), which are the Masked-TreeSHAP values tree ensembles expose
    without adding a separate dependency — per ADR-0004's rationale.
    """

    def __init__(self, booster: Booster, feature_names: Sequence[str] = FEATURE_NAMES) -> None:
        self._booster = booster
        self._feature_names = tuple(feature_names)

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        import numpy as np
        from xgboost import DMatrix

        row = np.asarray(
            [[float(sofa.severity()), float(age), float(len(comorbidities))]],
            dtype=np.float64,
        )
        probability = float(self._booster.predict(DMatrix(row))[0])
        contributions = self._booster.predict(DMatrix(row), pred_contribs=True)[0]
        attribution = {
            name: round(float(contributions[i]), 4)
            for i, name in enumerate(self._feature_names)
        }
        return SurvivalPrediction(
            probability=round(probability, 4),
            attribution=attribution,
        )


# Module-level establishment cache: the dataset and seed are fixed, so within one process
# the trained model is established once and reused by every demonstration consumer.
_ESTABLISHED: dict[tuple[int, Path, Path], tuple[TrainedSurvivalModel, ValidationReport]] = {}


def establish_survival_model(
    *,
    seed: int = SPLIT_SEED,
    x_csv: Path = X_TRAIN_CSV,
    y_csv: Path = Y_TRAIN_CSV,
) -> tuple[TrainedSurvivalModel, ValidationReport]:
    """Train, hold-out evaluate, gate, and return the servable survival model.

    Requires the ``model`` optional dependency (xgboost). Raises
    :class:`ModelValidationError` when the validation gate fails — callers (the CLI, the
    Simulation Run) must refuse to demonstrate in that case.
    """
    key = (seed, x_csv, y_csv)
    if key in _ESTABLISHED:
        return _ESTABLISHED[key]

    try:
        import numpy as np

        rows = _load_rows(x_csv, y_csv)
        if not rows:
            raise ModelValidationError("the dataset has no usable rows")
        train, test = _stratified_split(rows, seed, TRAIN_FRACTION)
        features = [
            [r.sofa, r.age, float(r.comorbidity_count)] for r in train
        ]
        targets = [r.survival for r in train]
        booster = fit_booster(features, targets, seed=seed)

        test_matrix = np.asarray(
            [[r.sofa, r.age, float(r.comorbidity_count)] for r in test],
            dtype=np.float64,
        )
        from xgboost import DMatrix

        y_prob = list(booster.predict(DMatrix(test_matrix)))
        y_true = [r.survival for r in test]
        report = validation_report(
            seed=seed, n_train=len(train), y_true=y_true, y_prob=y_prob
        )
    except ImportError as exc:  # xgboost not installed
        raise ModelValidationError(
            "the survival model harness needs the 'model' extras — "
            "run `pip install -e '.[model]'`"
        ) from exc

    if not report.passed():
        raise ModelValidationError(
            "survival model FAILED validation — demonstrations are blocked:\n"
            + report.describe()
            + "\n  reasons: "
            + "; ".join(report._gate_reasons())  # noqa: SLF001
        )

    model = TrainedSurvivalModel(booster)
    _ESTABLISHED[key] = (model, report)
    return model, report
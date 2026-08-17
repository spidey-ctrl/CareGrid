"""Tests for the survival-model harness (ticket 08).

The metric maths, the validation gate, and the dataset plumbing are pure functions and
are tested hermetically. The training/e2e tests exercise the real gradient-boosted tree
against a tiny synthetic dataset (never the real 3600-row file), so they are skipped
when the optional ``model`` dependency (xgboost) is absent — in line with the spec's
"no test requires the trained model or the dataset".
"""

from pathlib import Path

import pytest

from caregrid.sofa import Sofa
from caregrid.survival_model import (
    AUC_MIN,
    CALIBRATION_MEAN_MAX,
    TRAIN_FRACTION,
    CalibrationBin,
    ModelValidationError,
    TrainedSurvivalModel,
    ValidationReport,
    _Row,
    _load_rows,
    _stratified_split,
    brier_score,
    decile_calibration,
    establish_survival_model,
    fit_booster,
    roc_auc,
    validation_report,
)


def _bins(diffs: tuple[float, ...], predicted: float = 0.6, observed: float = 0.5) -> tuple[CalibrationBin, ...]:
    return tuple(
        CalibrationBin(
            index=i + 1,
            count=10,
            predicted=predicted + d / 2,
            observed=observed + d / 2,
            diff=d,
        )
        for i, d in enumerate(diffs)
    )


# --------------------------------------------------------------------------------------
# The metric maths
# --------------------------------------------------------------------------------------


def test_roc_auc_perfect_worst_and_random() -> None:
    y_true = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    assert roc_auc(y_true, [0.9, 0.8, 0.7, 0.3, 0.2, 0.1]) == pytest.approx(1.0)
    assert roc_auc(y_true, [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]) == pytest.approx(0.0)
    assert roc_auc(y_true, [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.5)


def test_roc_auc_hand_computed_with_a_tie() -> None:
    # the 0.5 pair straddles the two classes, so the tie is not perfectly separable:
    # positives at ranks 2.5 and 4 → (6.5 − 3) / 4 = 0.875
    y_true = [1.0, 1.0, 0.0, 0.0]
    y_prob = [0.7, 0.5, 0.5, 0.2]
    assert roc_auc(y_true, y_prob) == pytest.approx(0.875)


def test_roc_auc_degenerate_single_class() -> None:
    assert roc_auc([1.0, 1.0, 1.0], [0.2, 0.5, 0.8]) == pytest.approx(0.5)


def test_brier_score_hand_values() -> None:
    assert brier_score([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert brier_score([1.0, 0.0], [0.5, 0.5]) == pytest.approx(0.25)


def test_decile_calibration_bins_are_equal_count_and_report_diffs() -> None:
    n = 20
    y_prob = [i / 20 for i in range(1, n + 1)]
    y_true = [1.0 if i % 2 else 0.0 for i in range(n)]
    bins = decile_calibration(y_true, y_prob, bins=10)
    assert len(bins) == 10
    assert all(bin_.count == 2 for bin_ in bins)
    assert bins[0].index == 1 and bins[-1].index == 10
    # highest-probability decile holds the two largest predictions, 0.95 and 1.0,
    # whose outcomes (i=18 → 0, i=19 → 1) average to an observed rate of 0.5
    assert bins[-1].predicted == pytest.approx(0.975)
    assert bins[-1].observed == pytest.approx(0.5)
    assert bins[-1].diff == pytest.approx(0.475)


def test_validation_report_assembles_metrics() -> None:
    y_true = [1.0, 1.0, 0.0, 0.0]
    y_prob = [0.9, 0.7, 0.3, 0.1]
    report = validation_report(seed=7, n_train=800, y_true=y_true, y_prob=y_prob)
    assert report.seed == 7
    assert report.n_train == 800
    assert report.n_test == 4
    assert report.auc == pytest.approx(1.0)
    assert report.brier <= 0.25


# --------------------------------------------------------------------------------------
# The validation gate
# --------------------------------------------------------------------------------------


def test_gate_passes_clean_report() -> None:
    report = ValidationReport(
        seed=1,
        n_train=800,
        n_test=200,
        auc=AUC_MIN + 0.1,
        brier=0.12,
        calibration=_bins((0.01,) * 10),
    )
    assert report.passed()


def test_gate_blocks_low_auc() -> None:
    report = ValidationReport(
        seed=1,
        n_train=800,
        n_test=200,
        auc=AUC_MIN - 0.01,
        brier=0.2,
        calibration=_bins((0.01,) * 10),
    )
    assert not report.passed()
    assert "AUC" in report.describe()


def test_gate_blocks_bad_mean_calibration_error() -> None:
    report = ValidationReport(
        seed=1,
        n_train=800,
        n_test=200,
        auc=0.9,
        brier=0.12,
        calibration=_bins((0.15,) * 10),  # mean error 0.15 ≫ tolerance
    )
    assert not report.passed()


def test_gate_is_noise_aware_across_deciles() -> None:
    # individual deciles stray past ±5% yet the mean stays within tolerance — this
    # decile-by-decile scatter is exactly the hold-out sampling noise the gate was
    # amended to tolerate (issue #10)
    report = ValidationReport(
        seed=1,
        n_train=800,
        n_test=200,
        auc=0.9,
        brier=0.12,
        calibration=_bins((0.02, 0.03, 0.05, 0.02, 0.03, 0.04, 0.05, 0.04, 0.03, 0.02)),
    )
    assert report.mean_calibration_error == pytest.approx(0.033)
    assert report.passed()


# --------------------------------------------------------------------------------------
# Dataset plumbing
# --------------------------------------------------------------------------------------


def _write_synthetic(root: Path, *, noise: bool = False) -> tuple[Path, Path]:
    """A tiny deterministic ICU-style dataset: survival separable from SOFA + age.

    With ``noise`` the outcome is decoupled from the features, so the trained model is
    guaranteed to fail the gate — used to prove demonstrations get blocked.
    """
    root.mkdir(parents=True, exist_ok=True)
    x_csv = root / "X.csv"
    y_csv = root / "Y.csv"
    rows = [
        (i % 25, 40 + (i % 45)) for i in range(400)
    ]
    with x_csv.open("w") as f:
        f.write("SOFA,Age\n")
        for sofa, age in rows:
            f.write(f"{sofa},{age}\n")
    with y_csv.open("w") as f:
        f.write("In-hospital_death\n")
        for i, (sofa, age) in enumerate(rows):
            if noise:
                death = (i * 7) % 2
            else:
                death = 0 if 0.9 - 0.03 * sofa - 0.004 * age > 0 else 1
            f.write(f"{death}\n")
    return x_csv, y_csv


def test_load_rows_handles_na_and_target_inversion(tmp_path: Path) -> None:
    x = tmp_path / "X.csv"
    y = tmp_path / "Y.csv"
    x.write_text("SOFA,Age\n-1,64\n5,\n10,\n")
    y.write_text("In-hospital_death\n0\n1\n1\n")
    rows = _load_rows(x, y)
    assert rows[0].sofa != rows[0].sofa  # NaN
    assert rows[0].survival == 1.0  # death 0 → survival 1
    assert rows[1].age != rows[1].age  # NaN
    assert rows[2].survival == 0.0  # death 1 → survival 0
    assert rows[2].comorbidity_count == 0


def test_stratified_split_preserves_class_ratio(tmp_path: Path) -> None:
    x_csv, y_csv = _write_synthetic(tmp_path / "split")
    rows = _load_rows(x_csv, y_csv)
    first = [(r.sofa, r.survival) for r in _stratified_split(rows, seed=5, fraction=0.8)[0]]
    second = [(r.sofa, r.survival) for r in _stratified_split(rows, seed=5, fraction=0.8)[0]]
    assert first == second
    half = _stratified_split(rows, seed=5, fraction=0.5)
    survival_train = [r.survival for r in half[0]]
    survival_all = [r.survival for r in rows]
    train_rate = sum(survival_train) / len(survival_train)
    all_rate = sum(survival_all) / len(survival_all)
    assert train_rate == pytest.approx(all_rate, abs=0.05)


# --------------------------------------------------------------------------------------
# End-to-end: training, serving, gate (needs the optional xgboost dependency)
# --------------------------------------------------------------------------------------

# ``establish_survival_model`` always enforces the gate, and on this small synthetic
# sample the ±5% per-decile tolerance is swamped by binomial hold-out noise — so the
# training/serving mechanics are exercised through the building blocks directly, while
# the gate's own behaviour is unit-tested above and its happy path is deliberately not
# fabricated.


def _trained(
    tmp_path: Path, *, noise: bool = False
) -> tuple[TrainedSurvivalModel, list[float], list[_Row]]:
    pytest.importorskip("xgboost")
    import numpy as np
    from xgboost import DMatrix

    x_csv, y_csv = _write_synthetic(tmp_path / "data", noise=noise)
    rows = _load_rows(x_csv, y_csv)
    train, test = _stratified_split(rows, seed=123, fraction=TRAIN_FRACTION)
    features = [[r.sofa, r.age, float(r.comorbidity_count)] for r in train]
    booster = fit_booster(features, [r.survival for r in train], seed=123)
    model = TrainedSurvivalModel(booster)
    test_matrix = np.asarray(
        [[r.sofa, r.age, float(r.comorbidity_count)] for r in test], dtype=np.float64
    )
    y_prob = list(booster.predict(DMatrix(test_matrix)))
    return model, y_prob, test


def test_training_serves_through_the_adapter(tmp_path: Path) -> None:
    model, _, _ = _trained(tmp_path)
    prediction = model.predict(Sofa(3, 1, 2, 2, 3, 1), 64, ("diabetes",))
    assert 0.0 <= prediction.probability <= 1.0
    # SHAP contributions live in the log-odds margin, so they are bounded by nothing
    # tighter than the margin itself — but each feature must be present and finite
    assert set(prediction.attribution) == {"sofa", "age", "comorbidity_count"}
    assert all(value == value for value in prediction.attribution.values())


def test_validation_report_over_real_predictions(tmp_path: Path) -> None:
    pytest.importorskip("xgboost")
    _, y_prob, test = _trained(tmp_path)
    report = validation_report(
        seed=123, n_train=320, y_true=[r.survival for r in test], y_prob=y_prob
    )
    assert report.seed == 123
    assert report.n_test == len(test)
    assert 0.0 <= report.auc <= 1.0
    assert 0.0 <= report.brier <= 0.25
    assert len(report.calibration) == 10
    assert report.describe().startswith("Survival model validation report")


def test_training_is_reproducible_from_the_recorded_seed(tmp_path: Path) -> None:
    pytest.importorskip("xgboost")
    x_csv, y_csv = _write_synthetic(tmp_path / "a")
    rows = _load_rows(x_csv, y_csv)
    train, _ = _stratified_split(rows, seed=99, fraction=TRAIN_FRACTION)
    features = [[r.sofa, r.age, float(r.comorbidity_count)] for r in train]
    targets = [r.survival for r in train]
    first = TrainedSurvivalModel(fit_booster(features, targets, seed=99))
    second = TrainedSurvivalModel(fit_booster(features, targets, seed=99))
    p1 = first.predict(Sofa(3, 1, 2, 2, 3, 1), 64, ())
    p2 = second.predict(Sofa(3, 1, 2, 2, 3, 1), 64, ())
    assert p1.probability == p2.probability
    assert p1.attribution == p2.attribution


def test_establish_blocks_when_the_gate_fails(tmp_path: Path) -> None:
    pytest.importorskip("xgboost")
    x_csv, y_csv = _write_synthetic(tmp_path / "noisy", noise=True)
    with pytest.raises(ModelValidationError, match="FAILED validation"):
        establish_survival_model(seed=2026, x_csv=x_csv, y_csv=y_csv)


def test_trained_model_attribution_tracks_severity(tmp_path: Path) -> None:
    model, _, _ = _trained(tmp_path)
    mild = model.predict(Sofa(1, 1, 1, 1, 1, 1), 40, ())
    severe = model.predict(Sofa(4, 4, 4, 4, 4, 4), 80, ())
    assert severe.probability < mild.probability
    assert severe.attribution["sofa"] < mild.attribution["sofa"]
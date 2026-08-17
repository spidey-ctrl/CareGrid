import { useState } from "react";
import type { QueueEntry, RankPoint } from "../types";
import { fmtMinutes } from "../format";
import { FactorBar } from "./FactorBar";
import { MovementBadge } from "./MovementBadge";
import { ShapList } from "./ShapList";
import { getHistory } from "../api";

function whyThisRank(entry: QueueEntry): string {
  return (
    `why #${entry.rank} — score ${entry.score.toFixed(4)} (rounds to tier ` +
    `${entry.score.toFixed(2)}) = sev ${entry.severity_factor.toFixed(3)} + ` +
    `surv ${entry.survival_factor.toFixed(3)} + wait ${entry.waiting_factor.toFixed(3)} · ` +
    `p_surv ${entry.survival_probability.toFixed(3)}`
  );
}

export function EntryRow({
  entry,
  showMovement,
}: {
  entry: QueueEntry;
  showMovement: boolean;
}) {
  const [history, setHistory] = useState<RankPoint[] | null>(null);
  const [open, setOpen] = useState(false);

  async function toggleHistory() {
    if (history === null) {
      setHistory(await getHistory(entry.patient_id));
    }
    setOpen((was) => !was);
  }

  const tieBreak =
    entry.tie_break_reason === null ? null : (
      <span className="tie-break" title="Tie-Break Cascade reasoning">
        {entry.tie_break_reason}
      </span>
    );

  return (
    <>
      <tr className="entry-row" onClick={toggleHistory} title="click to view rank history">
        <td className="col-rank">
          <span className="rank-number">#{entry.rank}</span>
          {showMovement && <MovementBadge movement={entry.movement} />}
        </td>
        <td className="col-patient">
          <span className="patient-id">{entry.patient_id}</span>
          <span className="wait-label">waiting {fmtMinutes(entry.waiting_minutes)}</span>
        </td>
        <td className="col-score">
          <span className="score">{entry.score.toFixed(4)}</span>
        </td>
        <td className="col-factors">
          <FactorBar
            label="S"
            value={entry.severity_factor}
            tone="severity"
            title={`Severity (SOFA) factor ${entry.severity_factor.toFixed(3)}`}
          />
          <FactorBar
            label="V"
            value={entry.survival_factor}
            tone="survival"
            title={`Survival factor ${entry.survival_factor.toFixed(3)}`}
          />
          <FactorBar
            label="W"
            value={entry.waiting_factor}
            tone="waiting"
            title={`Waiting factor ${entry.waiting_factor.toFixed(3)}`}
          />
        </td>
        <td className="col-shap">
          <ShapList entry={entry} />
        </td>
        <td className="col-why">
          <div className="why-this-rank">{whyThisRank(entry)}</div>
          {tieBreak}
        </td>
      </tr>
      {open && history !== null && (
        <tr className="history-row">
          <td colSpan={6}>
            <div className="history-panel">
              <span className="history-title">rank history</span>
              {history.map((point) => (
                <span key={point.snapshot_id} className="history-point">
                  #{point.rank} <em>{point.trigger}</em>
                </span>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
import type { QueueEntry } from "../types";
import { EntryRow } from "./EntryRow";

export function QueueTable({
  queue,
  showMovement,
}: {
  queue: QueueEntry[];
  showMovement: boolean;
}) {
  return (
    <table className="queue-table">
      <thead>
        <tr>
          <th className="col-rank">rank</th>
          <th className="col-patient">patient</th>
          <th className="col-score">priority score</th>
          <th className="col-factors">factors (sev / surv / wait)</th>
          <th className="col-shap">SHAP attribution</th>
          <th className="col-why">why this rank</th>
        </tr>
      </thead>
      <tbody>
        {queue.map((entry) => (
          <EntryRow key={entry.entry_id} entry={entry} showMovement={showMovement} />
        ))}
      </tbody>
    </table>
  );
}
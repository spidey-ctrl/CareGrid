import type { TrailSummary } from "../types";

export function ReplayBar({
  trail,
  position,
  onChange,
}: {
  trail: TrailSummary[];
  position: number;
  onChange: (position: number) => void;
}) {
  const max = trail.length;
  const live = position === max;
  const current = live ? null : trail[position];

  return (
    <div className="replay-bar">
      <span className="replay-title">replay audit trail</span>
      <span className={`replay-current ${live ? "replay-live" : ""}`}>
        {live ? "LIVE" : current?.label}
      </span>
      <input
        type="range"
        className="replay-slider"
        min={0}
        max={max}
        value={position}
        aria-label="replay position"
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="replay-meta">
        {trail.length} record{trail.length === 1 ? "" : "s"} · drag to walk history
      </span>
    </div>
  );
}
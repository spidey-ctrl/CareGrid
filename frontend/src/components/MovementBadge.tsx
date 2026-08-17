import type { Movement, QueueEntry } from "../types";

const META: Record<Movement, { glyph: string; label: string }> = {
  up: { glyph: "\u25B2", label: "moved up since the last snapshot" },
  down: { glyph: "\u25BC", label: "moved down since the last snapshot" },
  unchanged: { glyph: "\u2022", label: "unchanged since the last snapshot" },
  new: { glyph: "NEW", label: "not present in the last snapshot" },
};

export function MovementBadge({ movement }: { movement: QueueEntry["movement"] }) {
  if (!movement) return null;
  const meta = META[movement];
  return (
    <span className={`movement movement-${movement}`} title={meta.label}>
      {meta.glyph}
    </span>
  );
}
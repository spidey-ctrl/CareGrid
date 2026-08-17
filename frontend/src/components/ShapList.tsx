import type { QueueEntry } from "../types";

export function ShapList({ entry }: { entry: QueueEntry }) {
  const attributions = Object.entries(entry.survival_attribution).sort(
    (a, b) => Math.abs(b[1]) - Math.abs(a[1]),
  );
  const top = attributions.slice(0, 3);
  return (
    <div className="shap">
      {top.length === 0 ? (
        <span className="shap-none">—</span>
      ) : (
        top.map(([feature, value]) => (
          <span key={feature} className={`shap-chip ${value >= 0 ? "shap-pos" : "shap-neg"}`}>
            {feature} {value >= 0 ? "+" : ""}
            {value.toFixed(3)}
          </span>
        ))
      )}
    </div>
  );
}
export function FactorBar({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: number;
  tone: "severity" | "survival" | "waiting";
  title: string;
}) {
  const width = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="factor" title={title}>
      <span className="factor-label">{label}</span>
      <div className={`factor-track factor-track-${tone}`}>
        <div className="factor-fill" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}
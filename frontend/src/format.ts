export function fmtMinutes(minutes: number): string {
  const hours = minutes / 60;
  const days = Math.floor(hours / 24);
  const rest = Math.round(hours % 24);
  return days > 0 ? `${days}d ${rest}h` : `${rest}h`;
}

export function fmtClock(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
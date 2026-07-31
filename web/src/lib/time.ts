/** "3m", "2h", "5d" — sidebar timestamps stay one glance wide. */
export function relativeTime(epochSeconds: number, now = Date.now()): string {
  const seconds = Math.max(0, (now - epochSeconds * 1000) / 1000);
  if (seconds < 45) return "just now";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 7) return `${Math.round(days)}d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

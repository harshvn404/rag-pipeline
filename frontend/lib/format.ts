export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";

  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  const maximumFractionDigits = value >= 10 || index === 0 ? 0 : 1;

  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(value)} ${units[index]}`;
}

export function formatScore(score: number): string {
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  }).format(score);
}

export function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value;
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

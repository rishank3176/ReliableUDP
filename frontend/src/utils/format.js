export const PROTOCOL_LABELS = {
  stop_and_wait: "Stop and Wait",
  go_back_n: "Go Back N",
  selective_repeat: "Selective Repeat",
};

export const STATUS_LABELS = {
  queued: "Queued",
  initializing: "Initializing",
  transferring: "Transferring",
  verifying: "Verifying",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const ACTIVE_STATUSES = new Set(["queued", "initializing", "transferring", "verifying"]);

export function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const size = Number(value);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${trim(size / 1024)} KB`;
  return `${trim(size / (1024 * 1024))} MB`;
}

export function formatRate(bps) {
  if (bps === null || bps === undefined || Number.isNaN(Number(bps))) return "—";
  const rate = Number(bps);
  if (rate < 1024) return `${rate.toFixed(0)} B/s`;
  if (rate < 1024 * 1024) return `${trim(rate / 1024)} KB/s`;
  return `${trim(rate / (1024 * 1024))} MB/s`;
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return "—";
  const value = Number(seconds);
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(2)} s`;
  const minutes = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return `${minutes}m ${rest}s`;
}

export function formatRtt(milliseconds) {
  if (milliseconds === null || milliseconds === undefined || Number.isNaN(Number(milliseconds))) {
    return "—";
  }
  const value = Number(milliseconds);
  return `${value < 10 ? value.toFixed(2) : value.toFixed(1)} ms`;
}

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(digits)}%`;
}

export function formatClock(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}

export function protocolLabel(protocol) {
  return PROTOCOL_LABELS[protocol] || protocol || "—";
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}

function trim(value) {
  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return value.toFixed(digits);
}

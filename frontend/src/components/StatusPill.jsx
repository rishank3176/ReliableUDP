import { statusLabel } from "../utils/format";

const TONES = {
  ok: "bg-good/15 text-good",
  warn: "bg-warn/15 text-warn",
  bad: "bg-bad/15 text-bad",
  info: "bg-accent/15 text-accent",
  idle: "bg-white/5 text-faint",
};

export default function StatusPill({ tone = "idle", children }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${TONES[tone] || TONES.idle}`}>
      {children}
    </span>
  );
}

export function statusTone(status) {
  if (status === "completed") return "ok";
  if (status === "failed") return "bad";
  if (status === "cancelled") return "warn";
  if (status === "transferring" || status === "verifying" || status === "initializing") return "info";
  return "idle";
}

export function StatusBadge({ status }) {
  return <StatusPill tone={statusTone(status)}>{statusLabel(status)}</StatusPill>;
}

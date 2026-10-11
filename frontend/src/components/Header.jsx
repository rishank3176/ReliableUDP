import StatusPill from "./StatusPill";

export default function Header({ health, healthError, onRefresh, refreshing }) {
  const receiver = health?.udp_receiver;
  const apiTone = healthError ? "bad" : health ? "ok" : "idle";
  const udpTone = receiver?.running ? "ok" : receiver?.error ? "bad" : "warn";
  return (
    <header className="border-b border-line bg-ink/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-accent">Computer Networks</p>
          <h1 className="mt-1 text-2xl font-semibold text-white sm:text-3xl">ReliableUDP</h1>
          <p className="text-sm text-faint">Reliable File Transfer Protocol over UDP</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={apiTone}>API {healthError ? "unreachable" : health ? "online" : "checking"}</StatusPill>
          <StatusPill tone={udpTone}>
            UDP receiver {receiver?.running ? `listening on ${receiver.port}` : receiver?.error || "not running"}
          </StatusPill>
          <button type="button" className="btn-ghost" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Checking…" : "Refresh health"}
          </button>
        </div>
      </div>
    </header>
  );
}

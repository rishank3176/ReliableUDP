import { StatusBadge } from "./StatusPill";
import { formatBytes, formatDuration, formatRate, formatRtt, protocolLabel } from "../utils/format";

export default function LiveMonitor({ transfer, onCancel, cancelling }) {
  if (!transfer) {
    return (
      <section className="card flex min-h-[28rem] flex-col justify-center p-6 text-center">
        <h2 className="text-lg font-semibold text-white">Live transfer monitor</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-faint">
          Start a transfer to watch sequence progress, retransmissions, throughput, and round-trip time from the running UDP sender.
        </p>
      </section>
    );
  }
  const active = ["queued", "initializing", "transferring", "verifying"].includes(transfer.status);
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Live transfer monitor</h2>
          <p className="mt-1 break-all font-mono text-xs text-faint">{transfer.id}</p>
        </div>
        <StatusBadge status={transfer.status} />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Info label="File" value={transfer.filename} />
        <Info label="Size" value={formatBytes(transfer.file_size)} />
        <Info label="Protocol" value={protocolLabel(transfer.protocol)} />
        <Info label="Window" value={String(transfer.window_size)} />
      </dl>
      <div className="mt-5">
        <div className="mb-1 flex justify-between text-xs text-faint">
          <span>Progress</span>
          <span>{Number(transfer.progress || 0).toFixed(1)}%</span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-ink" role="progressbar" aria-valuenow={transfer.progress || 0} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.min(100, transfer.progress || 0)}%` }} />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Bytes acknowledged" value={formatBytes(transfer.bytes_acked)} />
        <Stat label="Packets acknowledged" value={transfer.packets_acked ?? "—"} />
        <Stat label="Retransmissions" value={transfer.retransmissions ?? "—"} />
        <Stat label="Current throughput" value={formatRate(transfer.current_throughput_bps)} />
        <Stat label="Average RTT" value={formatRtt(transfer.average_rtt_ms)} />
        <Stat label="Elapsed" value={formatDuration(transfer.duration_seconds)} />
      </div>
      {transfer.error && (
        <p className="mt-4 rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{transfer.error}</p>
      )}
      {transfer.integrity === "verified" && (
        <p className="mt-4 rounded-lg border border-good/40 bg-good/10 px-3 py-2 text-sm text-good">
          SHA256 verified. The reconstructed file matches the original.
        </p>
      )}
      <div className="mt-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-faint">Recent protocol events</h3>
        {transfer.events?.length ? (
          <ul className="mt-2 max-h-36 space-y-1 overflow-auto font-mono text-xs text-mist">
            {transfer.events.map((event, index) => (
              <li key={`${event.t}-${index}`}>
                {event.t.toFixed ? event.t.toFixed(3) : event.t}s · {event.message}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-faint">No events yet.</p>
        )}
      </div>
      {active && (
        <button type="button" className="btn-ghost mt-4" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Cancelling…" : "Cancel transfer"}
        </button>
      )}
    </section>
  );
}

function Info({ label, value }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-faint">{label}</dt>
      <dd className="mt-1 break-all text-mist">{value}</dd>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-line bg-panel2 px-3 py-2">
      <p className="text-xs text-faint">{label}</p>
      <p className="mt-1 font-mono text-sm text-white">{value}</p>
    </div>
  );
}

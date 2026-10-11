import { formatDuration, formatPercent, formatRate, formatRtt } from "../utils/format";

export default function MetricCards({ transfer }) {
  const simulator = transfer?.simulator;
  const cards = [
    ["Throughput", formatRate(transfer?.average_throughput_bps), "Acknowledged file bytes / elapsed time"],
    ["Average RTT", formatRtt(transfer?.average_rtt_ms), transfer?.rtt_samples ? `${transfer.rtt_samples} samples` : "Unavailable until a clean ACK"],
    ["Transfer time", formatDuration(transfer?.duration_seconds), "Start through completion or failure"],
    ["Retransmissions", transfer ? String(transfer.retransmissions) : "—", "Extra DATA sends after the first attempt"],
    [
      "Simulated loss",
      simulator?.drop_rate === null || simulator?.drop_rate === undefined ? "—" : formatPercent(simulator.drop_rate * 100),
      simulator ? `${simulator.dropped} dropped / ${simulator.attempted} submitted` : "No simulator sample",
    ],
    [
      "Integrity",
      integrityLabel(transfer?.integrity),
      transfer?.received_sha256 ? transfer.received_sha256.slice(0, 16) + "…" : "SHA256 after reconstruction",
    ],
  ];
  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map(([title, value, hint]) => (
        <article key={title} className="card p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-faint">{title}</h3>
          <p className="mt-2 font-mono text-2xl text-white">{value}</p>
          <p className="mt-1 text-xs text-faint">{hint}</p>
        </article>
      ))}
    </section>
  );
}

function integrityLabel(integrity) {
  if (integrity === "verified") return "Verified";
  if (integrity === "mismatch") return "Mismatch";
  if (integrity === "not_checked") return "Not checked";
  if (!integrity) return "—";
  return "Pending";
}

import { downloadUrl } from "../services/api";
import { StatusBadge } from "./StatusPill";
import { formatBytes, formatClock, formatDuration, formatRate, protocolLabel } from "../utils/format";

export default function HistoryTable({ transfers, onSelect }) {
  return (
    <section className="card p-5">
      <h2 className="text-lg font-semibold text-white">Transfer history</h2>
      <p className="mt-1 text-sm text-faint">History is kept in memory for this backend process.</p>
      {transfers.length === 0 ? (
        <p className="mt-6 text-sm text-faint">No transfers yet.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="py-2 pr-3">File</th>
                <th className="py-2 pr-3">Protocol</th>
                <th className="py-2 pr-3">When</th>
                <th className="py-2 pr-3">Size</th>
                <th className="py-2 pr-3">Duration</th>
                <th className="py-2 pr-3">Throughput</th>
                <th className="py-2 pr-3">Retries</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Integrity</th>
                <th className="py-2">File</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((transfer) => (
                <tr key={transfer.id} className="border-t border-line">
                  <td className="py-2 pr-3">
                    <button type="button" className="text-left text-accent underline-offset-2 hover:underline" onClick={() => onSelect(transfer.id)}>
                      {transfer.filename}
                    </button>
                  </td>
                  <td className="py-2 pr-3">{protocolLabel(transfer.protocol)}</td>
                  <td className="py-2 pr-3 whitespace-nowrap">{formatClock(transfer.created_at)}</td>
                  <td className="py-2 pr-3">{formatBytes(transfer.file_size)}</td>
                  <td className="py-2 pr-3">{formatDuration(transfer.duration_seconds)}</td>
                  <td className="py-2 pr-3">{formatRate(transfer.average_throughput_bps)}</td>
                  <td className="py-2 pr-3">{transfer.retransmissions}</td>
                  <td className="py-2 pr-3">
                    <StatusBadge status={transfer.status} />
                  </td>
                  <td className="py-2 pr-3">{transfer.integrity}</td>
                  <td className="py-2">
                    {transfer.download_available ? (
                      <a className="text-accent hover:underline" href={downloadUrl(transfer.id)}>
                        Download
                      </a>
                    ) : (
                      <span className="text-faint">Unavailable</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

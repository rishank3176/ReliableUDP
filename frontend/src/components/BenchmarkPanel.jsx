import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDuration, formatRate, formatRtt, protocolLabel } from "../utils/format";

export default function BenchmarkPanel({ benchmark, running, onRun, disabled }) {
  const results = benchmark?.results || [];
  const chartData = results.map((row) => ({
    name: shortName(row.protocol),
    throughput: row.average_throughput_bps == null ? null : Number((row.average_throughput_bps / 1024).toFixed(2)),
    rtt: row.average_rtt_ms,
    retransmissions: row.retransmissions,
    duration: row.duration_seconds,
  }));
  return (
    <section className="card p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Protocol comparison</h2>
          <p className="mt-1 max-w-3xl text-sm text-faint">
            The same file is sent with Stop and Wait, Go Back N, and Selective Repeat, one after another, using the loss, delay, corruption, window, chunk size, and timeout currently in the form. Results are measured. No protocol is assumed to win.
          </p>
        </div>
        <button type="button" className="btn-primary shrink-0" onClick={onRun} disabled={disabled || running}>
          {running ? "Comparison running…" : "Run protocol comparison"}
        </button>
      </div>
      {!benchmark && !running && (
        <p className="mt-6 text-sm text-faint">No comparison yet. Run one to fill the throughput, RTT, duration, and retransmission charts.</p>
      )}
      {benchmark?.error && <p className="mt-4 text-sm text-bad">{benchmark.error}</p>}
      {results.length > 0 && (
        <>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th className="py-2 pr-3">Protocol</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Throughput</th>
                  <th className="py-2 pr-3">RTT</th>
                  <th className="py-2 pr-3">Retransmissions</th>
                  <th className="py-2">Integrity</th>
                </tr>
              </thead>
              <tbody>
                {results.map((row) => (
                  <tr key={row.protocol} className="border-t border-line">
                    <td className="py-2 pr-3">{protocolLabel(row.protocol)}</td>
                    <td className="py-2 pr-3">{row.status}</td>
                    <td className="py-2 pr-3 font-mono">{formatDuration(row.duration_seconds)}</td>
                    <td className="py-2 pr-3 font-mono">{formatRate(row.average_throughput_bps)}</td>
                    <td className="py-2 pr-3 font-mono">{formatRtt(row.average_rtt_ms)}</td>
                    <td className="py-2 pr-3 font-mono">{row.retransmissions}</td>
                    <td className="py-2">{row.integrity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ChartCard title="Throughput (KB/s)" data={chartData} dataKey="throughput" />
            <ChartCard title="Average RTT (ms)" data={chartData} dataKey="rtt" />
            <ChartCard title="Retransmissions" data={chartData} dataKey="retransmissions" />
            <ChartCard title="Duration (seconds)" data={chartData} dataKey="duration" />
          </div>
          <p className="mt-4 text-xs text-faint">
            Differences depend on packet loss, delay, file size, chunk size, window size, and the acknowledgement timeout. On a lossless local link the gap can be small.
          </p>
        </>
      )}
    </section>
  );
}

function ChartCard({ title, data, dataKey }) {
  const hasValue = data.some((row) => row[dataKey] !== null && row[dataKey] !== undefined);
  return (
    <div className="rounded-xl border border-line bg-panel2 p-3">
      <h3 className="text-sm font-semibold text-mist">{title}</h3>
      {!hasValue ? (
        <p className="mt-6 text-sm text-faint">This measurement was not available for the completed runs.</p>
      ) : (
        <div className="mt-2 h-52">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid stroke="#2a3d5c" strokeDasharray="3 3" />
              <XAxis dataKey="name" stroke="#93a4c0" tick={{ fontSize: 12 }} />
              <YAxis stroke="#93a4c0" tick={{ fontSize: 12 }} />
              <Tooltip contentStyle={{ background: "#10192b", border: "1px solid #2a3d5c", color: "#d7e2f2" }} />
              <Bar dataKey={dataKey} fill="#7aa2ff" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function shortName(protocol) {
  if (protocol === "stop_and_wait") return "Stop-and-Wait";
  if (protocol === "go_back_n") return "Go-Back-N";
  if (protocol === "selective_repeat") return "Selective Repeat";
  return protocol;
}

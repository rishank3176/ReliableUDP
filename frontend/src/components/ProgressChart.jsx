import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export default function ProgressChart({ transfer }) {
  const samples = transfer?.samples || [];
  return (
    <section className="card p-5">
      <h2 className="text-lg font-semibold text-white">Transfer progress</h2>
      <p className="mt-1 text-sm text-faint">Percentage of original file bytes acknowledged over time.</p>
      {samples.length < 2 ? (
        <p className="mt-8 text-sm text-faint">Progress samples appear here while a transfer is running. They are recorded by the sender, not animated in the browser.</p>
      ) : (
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={samples}>
              <CartesianGrid stroke="#2a3d5c" strokeDasharray="3 3" />
              <XAxis dataKey="t" stroke="#93a4c0" tick={{ fontSize: 12 }} unit="s" />
              <YAxis stroke="#93a4c0" tick={{ fontSize: 12 }} domain={[0, 100]} unit="%" />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="progress" name="Progress" stroke="#3ee0c5" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

const tooltipStyle = {
  background: "#10192b",
  border: "1px solid #2a3d5c",
  borderRadius: "8px",
  color: "#d7e2f2",
};

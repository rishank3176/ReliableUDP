import { formatPercent } from "../utils/format";

export default function SimulationPanel({ transfer }) {
  const simulator = transfer?.simulator;
  return (
    <section className="card p-5">
      <h2 className="text-lg font-semibold text-white">Network simulation</h2>
      <p className="mt-1 text-sm text-faint">
        Loss, delay, and corruption are injected into real UDP datagrams so the reliability protocols can be observed recovering. Counts below come from the simulator, not from a guessed loss rate.
      </p>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Item label="Configured loss" value={transfer ? `${transfer.loss_percent}%` : "—"} />
        <Item label="Configured delay" value={transfer ? `${transfer.delay_ms} ms` : "—"} />
        <Item label="Configured corruption" value={transfer ? `${transfer.corruption_percent}%` : "—"} />
        <Item label="Measured drop rate" value={simulator?.drop_rate == null ? "—" : formatPercent(simulator.drop_rate * 100)} />
        <Item label="Datagrams dropped" value={simulator ? simulator.dropped : "—"} />
        <Item label="Datagrams corrupted" value={simulator ? simulator.corrupted : "—"} />
        <Item label="Data drops" value={simulator ? `${simulator.data_dropped} / ${simulator.data_attempted}` : "—"} />
        <Item label="Delay applied" value={simulator ? `${simulator.total_delay_ms} ms` : "—"} />
      </dl>
      <p className="mt-4 text-xs text-faint">
        With the built-in receiver, simulation covers sender data and control datagrams plus receiver acknowledgements. Drop rate uses dropped datagrams divided by datagrams submitted to the simulator. Data drops count only DATA categories.
      </p>
    </section>
  );
}

function Item({ label, value }) {
  return (
    <div className="rounded-xl border border-line bg-panel2 px-3 py-2">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-1 font-mono text-mist">{value}</dd>
    </div>
  );
}

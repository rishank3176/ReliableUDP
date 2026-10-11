import { PROTOCOL_LABELS } from "../utils/format";

const PROTOCOL_HELP = {
  stop_and_wait: "Sends one data packet and waits for its acknowledgement. The window is fixed at 1.",
  go_back_n: "Keeps several packets in flight and retransmits from the first missing packet after a timeout.",
  selective_repeat: "Acknowledges each packet and retransmits only the ones that were not acknowledged.",
};

export default function TransferForm({
  form,
  file,
  busy,
  onChange,
  onFile,
  onProtocol,
  onStart,
  onPreset,
}) {
  const stopAndWait = form.protocol === "stop_and_wait";
  const timeoutWarning = Number(form.ack_timeout_ms) < Number(form.delay_ms) + 150;
  return (
    <section className="card p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Transfer configuration</h2>
          <p className="text-sm text-faint">The file bytes travel over UDP. This form only starts and configures that transfer.</p>
        </div>
        <button type="button" className="btn-ghost shrink-0" onClick={onPreset} disabled={busy}>
          Demo settings
        </button>
      </div>
      <div className="space-y-4">
        <div>
          <label className="label" htmlFor="file">
            File
          </label>
          <input
            id="file"
            className="field file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1 file:text-sm file:font-semibold file:text-ink"
            type="file"
            onChange={(event) => onFile(event.target.files?.[0] || null)}
            disabled={busy}
          />
          <p className="mt-1 text-xs text-faint">
            {file ? `${file.name} · ${file.size.toLocaleString()} bytes` : "No file selected"}
          </p>
        </div>
        <div>
          <label className="label" htmlFor="protocol">
            Reliability protocol
          </label>
          <select
            id="protocol"
            className="field"
            value={form.protocol}
            disabled={busy}
            onChange={(event) => onProtocol(event.target.value)}
          >
            {Object.entries(PROTOCOL_LABELS).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-faint">{PROTOCOL_HELP[form.protocol]}</p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <NumberField
            id="window"
            label="Window size"
            value={stopAndWait ? 1 : form.window_size}
            min={1}
            max={32}
            disabled={busy || stopAndWait}
            onChange={(value) => onChange("window_size", value)}
            hint={stopAndWait ? "Disabled because Stop and Wait uses one outstanding packet." : "Outstanding packets."}
          />
          <NumberField id="chunk" label="Chunk size (bytes)" value={form.chunk_size} min={64} max={1400} disabled={busy} onChange={(value) => onChange("chunk_size", value)} />
          <NumberField id="timeout" label="ACK timeout (ms)" value={form.ack_timeout_ms} min={20} max={30000} disabled={busy} onChange={(value) => onChange("ack_timeout_ms", value)} />
          <NumberField id="retries" label="Max retries" value={form.max_retries} min={0} max={30} disabled={busy} onChange={(value) => onChange("max_retries", value)} />
          <div>
            <label className="label" htmlFor="host">
              Receiver host
            </label>
            <input id="host" className="field" value={form.receiver_host} disabled={busy} onChange={(event) => onChange("receiver_host", event.target.value)} />
          </div>
          <NumberField id="port" label="Receiver UDP port" value={form.receiver_port} min={1} max={65535} disabled={busy} onChange={(value) => onChange("receiver_port", value)} />
        </div>
        <Slider id="loss" label="Packet loss" value={form.loss_percent} unit="%" disabled={busy} onChange={(value) => onChange("loss_percent", value)} />
        <NumberField id="delay" label="Artificial delay bound (ms)" value={form.delay_ms} min={0} max={10000} disabled={busy} onChange={(value) => onChange("delay_ms", value)} />
        <Slider id="corruption" label="Packet corruption" value={form.corruption_percent} unit="%" disabled={busy} onChange={(value) => onChange("corruption_percent", value)} />
        {timeoutWarning && (
          <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">
            The acknowledgement timeout is close to the artificial delay. Receiver-side delay counts against the timer. A practical minimum here is {Number(form.delay_ms) + 150} ms.
          </p>
        )}
        <button type="button" className="btn-primary w-full" onClick={onStart} disabled={busy || !file}>
          {busy ? "Transfer in progress" : "Start transfer"}
        </button>
      </div>
    </section>
  );
}

function NumberField({ id, label, value, min, max, disabled, onChange, hint }) {
  return (
    <div>
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field"
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <p className="mt-1 text-xs text-faint">{hint}</p>}
    </div>
  );
}

function Slider({ id, label, value, unit, disabled, onChange }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="label mb-0" htmlFor={id}>
          {label}
        </label>
        <span className="font-mono text-sm text-accent">
          {value}
          {unit}
        </span>
      </div>
      <input
        id={id}
        className="w-full accent-accent"
        type="range"
        min="0"
        max="100"
        step="1"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

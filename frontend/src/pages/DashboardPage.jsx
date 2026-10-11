import { useCallback, useEffect, useRef, useState } from "react";
import BenchmarkPanel from "../components/BenchmarkPanel";
import Header from "../components/Header";
import HistoryTable from "../components/HistoryTable";
import LiveMonitor from "../components/LiveMonitor";
import MetricCards from "../components/MetricCards";
import ProgressChart from "../components/ProgressChart";
import SimulationPanel from "../components/SimulationPanel";
import TransferForm from "../components/TransferForm";
import {
  cancelTransfer,
  createTransfer,
  getBenchmark,
  getConfig,
  getHealth,
  getLatestBenchmark,
  getTransfer,
  getTransfers,
  startBenchmark,
} from "../services/api";
import { ACTIVE_STATUSES } from "../utils/format";

const INITIAL_FORM = {
  protocol: "go_back_n",
  window_size: 8,
  chunk_size: 1024,
  ack_timeout_ms: 500,
  max_retries: 8,
  receiver_host: "127.0.0.1",
  receiver_port: 9000,
  loss_percent: 0,
  delay_ms: 0,
  corruption_percent: 0,
};

export default function DashboardPage() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [form, setForm] = useState(INITIAL_FORM);
  const [file, setFile] = useState(null);
  const [transfer, setTransfer] = useState(null);
  const [history, setHistory] = useState([]);
  const [benchmark, setBenchmark] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [benchmarking, setBenchmarking] = useState(false);
  const savedWindow = useRef(8);
  const portSynced = useRef(false);

  const refreshHealth = useCallback(async () => {
    setRefreshing(true);
    try {
      const body = await getHealth();
      setHealth(body);
      setHealthError("");
      if (!portSynced.current && body.udp_receiver?.port) {
        portSynced.current = true;
        setForm((current) => ({
          ...current,
          receiver_port: body.udp_receiver.port,
          receiver_host: body.udp_receiver.host === "0.0.0.0" ? "127.0.0.1" : current.receiver_host,
        }));
      }
    } catch (err) {
      setHealth(null);
      setHealthError(err.message);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    getConfig()
      .then((config) => {
        setForm((current) => ({ ...current, ...config.defaults, receiver_port: current.receiver_port || config.defaults.receiver_port }));
      })
      .catch(() => {});
    getTransfers()
      .then((body) => setHistory(body.transfers || []))
      .catch(() => {});
    getLatestBenchmark()
      .then((body) => setBenchmark(body.benchmark))
      .catch(() => {});
  }, [refreshHealth]);

  useEffect(() => {
    const timer = setInterval(() => {
      refreshHealth();
    }, 8000);
    return () => clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    if (!transfer || !ACTIVE_STATUSES.has(transfer.status)) return undefined;
    const timer = setInterval(async () => {
      try {
        const next = await getTransfer(transfer.id);
        setTransfer(next);
        if (!ACTIVE_STATUSES.has(next.status)) {
          const listing = await getTransfers();
          setHistory(listing.transfers || []);
        }
      } catch (err) {
        setError(err.message);
      }
    }, 400);
    return () => clearInterval(timer);
  }, [transfer]);

  useEffect(() => {
    if (!benchmark || benchmark.status !== "running") return undefined;
    const timer = setInterval(async () => {
      try {
        const next = await getBenchmark(benchmark.id);
        setBenchmark(next);
        if (next.status !== "running") {
          setBenchmarking(false);
          const listing = await getTransfers();
          setHistory(listing.transfers || []);
        }
      } catch (err) {
        setError(err.message);
        setBenchmarking(false);
      }
    }, 700);
    return () => clearInterval(timer);
  }, [benchmark]);

  function updateField(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function updateProtocol(protocol) {
    setForm((current) => {
      if (protocol === "stop_and_wait") {
        savedWindow.current = Number(current.window_size) || 8;
        return { ...current, protocol, window_size: 1 };
      }
      const restored = current.protocol === "stop_and_wait" ? savedWindow.current : current.window_size;
      return { ...current, protocol, window_size: restored };
    });
  }

  function applyPreset() {
    setForm((current) => ({
      ...current,
      protocol: "selective_repeat",
      window_size: 8,
      chunk_size: 512,
      ack_timeout_ms: 500,
      max_retries: 10,
      loss_percent: 10,
      delay_ms: 40,
      corruption_percent: 2,
    }));
    setNotice("Demonstration settings loaded. They still run a real UDP transfer.");
  }

  async function handleStart() {
    setError("");
    setNotice("");
    if (!file) {
      setError("Choose a file before starting a transfer.");
      return;
    }
    const problem = validateForm(form);
    if (problem) {
      setError(problem);
      return;
    }
    const body = new FormData();
    body.append("file", file);
    appendSettings(body, form);
    setStarting(true);
    try {
      const created = await createTransfer(body);
      setTransfer(created);
      setNotice(`Transfer ${created.id.slice(0, 8)} started.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  async function handleCancel() {
    if (!transfer) return;
    setCancelling(true);
    try {
      const next = await cancelTransfer(transfer.id);
      setTransfer(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setCancelling(false);
    }
  }

  async function handleBenchmark() {
    setError("");
    setNotice("");
    const problem = validateForm(form);
    if (problem) {
      setError(problem);
      return;
    }
    const body = new FormData();
    if (file) body.append("file", file);
    const comparisonWindow = form.protocol === "stop_and_wait" ? savedWindow.current : form.window_size;
    appendSettings(body, form, comparisonWindow);
    body.append("generate_bytes", file ? "0" : "32768");
    setBenchmarking(true);
    try {
      const created = await startBenchmark(body);
      setBenchmark(created);
      setNotice(file ? "Comparison started with the selected file." : "Comparison started with a generated 32 KB test file.");
    } catch (err) {
      setBenchmarking(false);
      setError(err.message);
    }
  }

  async function inspect(id) {
    try {
      setTransfer(await getTransfer(id));
    } catch (err) {
      setError(err.message);
    }
  }

  const transferBusy = starting || (transfer && ACTIVE_STATUSES.has(transfer.status)) || benchmarking;

  return (
    <div className="min-h-screen">
      <Header health={health} healthError={healthError} onRefresh={refreshHealth} refreshing={refreshing} />
      <main className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-6">
        {error && (
          <div className="rounded-xl border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad" role="alert">
            {error}
          </div>
        )}
        {notice && <div className="rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent">{notice}</div>}
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <TransferForm
            form={form}
            file={file}
            busy={Boolean(transferBusy)}
            onChange={updateField}
            onFile={setFile}
            onProtocol={updateProtocol}
            onStart={handleStart}
            onPreset={applyPreset}
          />
          <LiveMonitor transfer={transfer} onCancel={handleCancel} cancelling={cancelling} />
        </div>
        <MetricCards transfer={transfer} />
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <SimulationPanel transfer={transfer} />
          <ProgressChart transfer={transfer} />
        </div>
        <BenchmarkPanel benchmark={benchmark} running={benchmarking || benchmark?.status === "running"} onRun={handleBenchmark} disabled={Boolean(transferBusy)} />
        <HistoryTable transfers={history} onSelect={inspect} />
      </main>
    </div>
  );
}

function appendSettings(body, form, windowSize) {
  body.append("protocol", form.protocol);
  const resolvedWindow = windowSize ?? (form.protocol === "stop_and_wait" ? 1 : form.window_size);
  body.append("window_size", String(resolvedWindow));
  body.append("chunk_size", String(form.chunk_size));
  body.append("ack_timeout_ms", String(form.ack_timeout_ms));
  body.append("max_retries", String(form.max_retries));
  body.append("receiver_host", form.receiver_host.trim());
  body.append("receiver_port", String(form.receiver_port));
  body.append("loss_percent", String(form.loss_percent));
  body.append("delay_ms", String(form.delay_ms));
  body.append("corruption_percent", String(form.corruption_percent));
}

function validateForm(form) {
  const checks = [
    [form.receiver_host.trim(), "Enter a receiver host."],
    [Number(form.receiver_port) >= 1 && Number(form.receiver_port) <= 65535, "Receiver port must be between 1 and 65535."],
    [Number(form.chunk_size) >= 64 && Number(form.chunk_size) <= 1400, "Chunk size must be between 64 and 1400 bytes."],
    [Number(form.window_size) >= 1 && Number(form.window_size) <= 32, "Window size must be between 1 and 32."],
    [Number(form.ack_timeout_ms) >= 20 && Number(form.ack_timeout_ms) <= 30000, "Acknowledgement timeout is out of range."],
    [Number(form.max_retries) >= 0 && Number(form.max_retries) <= 30, "Retry limit must be between 0 and 30."],
    [Number(form.loss_percent) >= 0 && Number(form.loss_percent) <= 100, "Packet loss must be between 0 and 100."],
    [Number(form.corruption_percent) >= 0 && Number(form.corruption_percent) <= 100, "Corruption must be between 0 and 100."],
    [Number(form.delay_ms) >= 0 && Number(form.delay_ms) <= 10000, "Delay must be between 0 and 10000 ms."],
  ];
  for (const [ok, message] of checks) {
    if (!ok) return message;
  }
  return "";
}

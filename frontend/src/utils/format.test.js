import test from "node:test";
import assert from "node:assert/strict";
import {
  formatBytes,
  formatDuration,
  formatPercent,
  formatRate,
  formatRtt,
  protocolLabel,
} from "./format.js";

test("formats bytes and leaves missing values blank", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.50 KB");
  assert.equal(formatBytes(null), "—");
});

test("formats throughput from payload bytes per second", () => {
  assert.equal(formatRate(2048), "2.00 KB/s");
  assert.equal(formatRate(undefined), "—");
});

test("formats durations and round-trip times", () => {
  assert.equal(formatDuration(0.25), "250 ms");
  assert.equal(formatDuration(1.5), "1.50 s");
  assert.equal(formatRtt(null), "—");
  assert.equal(formatRtt(12.34), "12.3 ms");
});

test("formats percentages and protocol names", () => {
  assert.equal(formatPercent(12.34), "12.3%");
  assert.equal(protocolLabel("selective_repeat"), "Selective Repeat");
});

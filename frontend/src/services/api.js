const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new Error("Cannot reach the ReliableUDP API. Start the backend on port 8000.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || body.error || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
      }
    } catch {
      detail = response.statusText;
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) return response;
  return response.json();
}

export function getHealth() {
  return request("/api/health");
}

export function getConfig() {
  return request("/api/config");
}

export function getTransfers() {
  return request("/api/transfers");
}

export function getTransfer(id) {
  return request(`/api/transfers/${id}`);
}

export function createTransfer(formData) {
  return request("/api/transfers", { method: "POST", body: formData });
}

export function cancelTransfer(id) {
  return request(`/api/transfers/${id}/cancel`, { method: "POST" });
}

export function startBenchmark(formData) {
  return request("/api/benchmark", { method: "POST", body: formData });
}

export function getBenchmark(id) {
  return request(`/api/benchmark/${id}`);
}

export function getLatestBenchmark() {
  return request("/api/benchmark");
}

export function downloadUrl(id) {
  return `${API_BASE}/api/transfers/${id}/download`;
}

/**
 * Data access for the SENTRA AI frontend.
 *
 * All traffic is same-origin: Next.js route handlers under `/api/*` proxy to the
 * Python backend (`sentinel.api.serve`) whose URL comes from `SENTRA_API_URL`.
 * Nothing secret is ever exposed to the browser, and no localhost address is
 * hardcoded in client code.
 */

const DEFAULT_WINDOW = '1h';

export const WINDOWS: { value: string; label: string }[] = [
  { value: '15m', label: 'Last 15 minutes' },
  { value: '1h', label: 'Last 1 Hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
];

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function withQuery(path: string, params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

async function unwrap<T>(res: Response): Promise<T> {
  let payload: { ok?: boolean; data?: T; error?: string } | null = null;
  try {
    payload = await res.json();
  } catch {
    throw new ApiError(`Malformed response (HTTP ${res.status})`, res.status);
  }
  if (!res.ok || payload?.ok === false) {
    throw new ApiError(
      payload?.error || `Request failed (HTTP ${res.status})`,
      res.status,
    );
  }
  if (!payload) {
    throw new ApiError('Empty response from the SENTRA backend', res.status);
  }
  return payload.data as T;
}

export async function apiGet<T>(
  path: string,
  params: Record<string, string | number | undefined | null> = {},
): Promise<T> {
  const res = await fetch(withQuery(path, params), {
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  });
  return unwrap<T>(res);
}

export async function apiPost<T>(
  path: string,
  body: Record<string, unknown> = {},
): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  return unwrap<T>(res);
}

export const dashboard = (window: string = DEFAULT_WINDOW) =>
  apiGet<import('./types').DashboardPayload>('/api/dashboard', { window });

export const fetchSeries = (window = DEFAULT_WINDOW) =>
  apiGet<{ ts: string[]; metrics: Record<string, (number | null)[]> }>('/api/series', { window });

export const fetchNetwork = (window = DEFAULT_WINDOW) =>
  apiGet<import('./types').NetworkSeries>('/api/network', { window });

export const fetchRisk = (window = '24h') =>
  apiGet<import('./types').RiskPayload>('/api/risk', { window });

export const fetchAnomalies = (window = '24h', limit = 100) =>
  apiGet<{ anomalies: import('./types').AnomalyRow[] }>('/api/anomalies', { window, limit });

export const fetchAlerts = (window = '24h', limit = 100) =>
  apiGet<{ alerts: import('./types').AlertRow[] }>('/api/alerts', { window, limit });

export const fetchProcesses = (limit = 100) =>
  apiGet<{ processes: import('./types').ProcessRow[] }>('/api/processes', { limit });

export const fetchLogs = (window = '24h', limit = 200) =>
  apiGet<{ logs: import('./types').LogRow[]; sources: string[] }>('/api/logs', { window, limit });

export const fetchTimeline = (limit = 20) =>
  apiGet<{ events: import('./types').TimelineEvent[] }>('/api/timeline', { limit });

export const fetchFleet = () =>
  apiGet<{ fleet: import('./types').FleetRow[] }>('/api/fleet');

export const fetchAgent = () => apiGet<import('./types').AgentStatus>('/api/agent');

export const fetchDevices = () =>
  apiGet<{ devices: import('./types').FleetRow[] }>('/api/devices');

export const fetchHealth = () =>
  apiGet<{ health: import('./types').HealthPayload; counts: Record<string, number> }>('/api/health');

export const fetchAnalytics = (window = '24h') =>
  apiGet<{
    summary: Record<string, unknown>;
    reliability: Record<string, number | string | null>;
    correlation: Record<string, unknown>[];
    hourly_profile: Record<string, unknown>[];
    rag_usage: Record<string, unknown>;
  }>('/api/analytics', { window });

export const fetchRag = () => apiGet<import('./types').RagPayload>('/api/rag');

export const fetchDocuments = () =>
  apiGet<{ documents: import('./types').DocumentRow[] }>('/api/documents');

export const investigate = (question: string, deviceId?: string) =>
  apiPost<Record<string, unknown>>('/api/investigate', { question, device_id: deviceId });

export const investigateAnomaly = (anomalyId: string, question?: string) =>
  apiPost<Record<string, unknown>>('/api/investigate-anomaly', {
    anomaly_id: anomalyId,
    question,
  });

export const ragAnswer = (query: string) => apiPost<Record<string, unknown>>('/api/rag-answer', { query });

export const ragRetrieve = (query: string, topK = 5) =>
  apiPost<Record<string, unknown>>('/api/rag-retrieve', { query, top_k: topK });

export const acknowledgeAnomaly = (anomalyId: string) =>
  apiPost<{ acknowledged: boolean }>('/api/ack-anomaly', { anomaly_id: anomalyId });

export const setAlertStatus = (alertId: string, status: string) =>
  apiPost<{ updated: boolean }>('/api/alert-status', { alert_id: alertId, status });

export const setDeviceStatus = (deviceId: string, status: string) =>
  apiPost<{ updated: boolean }>('/api/device-status', { device_id: deviceId, status });

export const runCycle = (deviceId?: string) =>
  apiPost<Record<string, unknown>>('/api/run-cycle', { device_id: deviceId });

export const trainModel = (deviceId?: string) =>
  apiPost<Record<string, unknown>>('/api/train-model', { device_id: deviceId });

export const seedDemo = (payload: Record<string, unknown> = {}) =>
  apiPost<Record<string, unknown>>('/api/demo/seed', {
    samples: 240,
    scenario: 'anomaly',
    seed: 7,
    train_model: true,
    include_document: true,
    ...payload,
  });

export const clearDemo = () => apiPost<Record<string, unknown>>('/api/demo/clear');

export const createPairingCode = () => apiPost<Record<string, unknown>>('/api/pairing-code');

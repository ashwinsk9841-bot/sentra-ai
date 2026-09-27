/**
 * Types mirroring the payloads produced by `sentinel/api/serve.py`.
 * These are the real shapes returned by the Python services.
 */

export type Tone = 'info' | 'success' | 'warning' | 'danger';

export interface SentraDevice {
  device_id: string;
  name: string;
  status: string | null;
  os_name: string | null;
  os_version: string | null;
  hostname: string | null;
  arch: string | null;
  agent_version: string | null;
  last_seen: string | null;
  risk_score: number | null;
  demo: boolean;
  scenario: string | null;
}

export interface MetricPoint {
  cpu_percent?: number | null;
  memory_percent?: number | null;
  disk_percent?: number | null;
  disk_read_mbps?: number | null;
  disk_write_mbps?: number | null;
  net_sent_mbps?: number | null;
  net_recv_mbps?: number | null;
  load_average?: number | null;
  process_count?: number | null;
}

export interface TelemetrySeries {
  ts: string[];
  metrics: Record<string, (number | null)[]>;
}

export interface NetworkSeries {
  ts: string[];
  sent_mbps: (number | null)[];
  recv_mbps: (number | null)[];
  latest: Record<string, number | string | null> | null;
}

export interface RiskDriver {
  key: string;
  label: string | null;
  value: number | null;
  weight?: number | null;
}

export interface RiskPayload {
  score: number | null;
  severity: string | null;
  summary: string | null;
  updated_at: string | null;
  trend: number | null;
  drivers: RiskDriver[];
  events?: Record<string, unknown>[];
}

export interface AnomalyRow {
  id: string;
  device_id: string;
  ts: string;
  metric: string;
  observed_value: number | null;
  expected_value: number | null;
  baseline_std: number | null;
  delta: number | null;
  ratio: number | null;
  model: string | null;
  anomaly_score: number | null;
  risk_score: number | null;
  severity: string | null;
  explanation: string | null;
  evidence: Record<string, unknown> | null;
  acknowledged: number | boolean | null;
}

export interface AlertRow {
  id: string;
  device_id: string;
  anomaly_id: string | null;
  ts: string;
  title: string | null;
  message: string | null;
  metric: string | null;
  severity: string | null;
  risk_score: number | null;
  status: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface TimelineEvent {
  id: string;
  ts: string | null;
  title: string;
  detail: string;
  level: string;
  tone: Tone;
  status: string;
  origin: string;
}

export interface ProcessRow {
  id: number;
  ts: string;
  pid: number;
  ppid: number | null;
  name: string;
  owner: string | null;
  status: string | null;
  cpu_percent: number | null;
  memory_percent: number | null;
  rss_mb: number | null;
  num_threads: number | null;
  create_time: string | null;
}

export interface LogRow {
  id: number;
  ts: string;
  source: string | null;
  level: string | null;
  message: string | null;
  logger_name: string | null;
  line_no: number | null;
  occurrences: number | null;
}

export interface DocumentRow {
  id: string;
  title: string | null;
  filename: string | null;
  source: string | null;
  status: string | null;
  size_bytes: number | null;
  char_count: number | null;
  chunk_count: number | null;
  pages: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FleetRow {
  device_id: string;
  name: string;
  status: string | null;
  os_name: string | null;
  agent_version: string | null;
  last_seen: string | null;
  last_seen_age_s: number | null;
  online: boolean;
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  risk_score: number | null;
  arch: string | null;
  hostname: string | null;
}

export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
  latency_ms?: number;
}

export interface HealthPayload {
  ok: boolean;
  checks: HealthCheck[];
  problems: string[];
  counts: Record<string, number>;
  backends: {
    name: string;
    connected: boolean;
    latency_ms: number;
    detail: string;
    mode?: string | null;
    error?: string | null;
  }[];
  rag: Record<string, unknown>;
}

export interface DashboardPayload {
  empty: boolean;
  window: string;
  window_label: string;
  generated_at?: string;
  device: SentraDevice | null;
  latest: Record<string, number | null> | null;
  metric_labels: Record<string, string>;
  metric_units: Record<string, string>;
  counts: Record<string, number>;
  severity_breakdown: Record<string, number>;
  risk: RiskPayload;
  series: TelemetrySeries;
  network: NetworkSeries;
  anomalies: AnomalyRow[];
  alerts: AlertRow[];
  timeline: TimelineEvent[];
  unread: number;
  model: Record<string, unknown>;
  health: HealthPayload;
  totals: Record<string, number>;
  demo: Record<string, unknown>;
  uptime_seconds: number | null;
  monitored_seconds: number | null;
  net_activity_mbps: number | null;
  reliability: Record<string, number | string | null>;
}

export interface AgentStatus {
  transport: Record<string, unknown>;
  collection: Record<string, unknown>;
  device: Record<string, unknown>;
  backend: Record<string, unknown>;
  data_boundary: string[];
}

export interface RagPayload {
  stats: Record<string, unknown>;
  usage: Record<string, unknown>;
  history: Record<string, unknown>[];
  documents: DocumentRow[];
}

/**
 * Presentation helpers.
 *
 * Sentra's own thresholds drive every badge so the UI never invents a health
 * state: `CRITICAL >= 85`, `HIGH >= 70`, `MEDIUM >= 45`, otherwise `LOW`.
 * The band label shown in a badge is the Sentra word for that band.
 */

export const COLORS = {
  cyan: '#00D9FF',
  blue: '#1677FF',
  violet: '#9B6CFF',
  green: '#00E5A0',
  amber: '#FFB020',
  red: '#FF4D5E',
  ink: '#F2F7FF',
  muted: '#8FA7C2',
} as const;

export type Accent = 'cyan' | 'violet' | 'green' | 'amber' | 'red' | 'blue';

export const ACCENT_HEX: Record<Accent, string> = {
  cyan: COLORS.cyan,
  blue: COLORS.blue,
  violet: COLORS.violet,
  green: COLORS.green,
  amber: COLORS.amber,
  red: COLORS.red,
};

/** Convert any backend metric to a finite number, or null when unusable. */
export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Format with a fixed decimal count, tolerating null. */
export function fmt(value: unknown, digits = 1, suffix = ''): string {
  const n = num(value);
  if (n === null) return '--';
  return `${n.toFixed(digits)}${suffix}`;
}

export function fmtInt(value: unknown): string {
  const n = num(value);
  if (n === null) return '--';
  return Math.round(n).toLocaleString('en-US');
}

/** Zero-padded integer, e.g. 3 -> "03" (used by the anomaly counter). */
export function fmtPadded(value: unknown, length = 2): string {
  const n = num(value);
  if (n === null) return '--'.padStart(length, '0');
  return String(Math.round(n)).padStart(length, '0');
}

/** Throughput in the most readable unit. */
export function fmtMbps(value: unknown): string {
  const n = num(value);
  if (n === null) return '--';
  if (n >= 1000) return `${(n / 1000).toFixed(2)} GB/s`;
  if (n >= 1) return `${n.toFixed(2)} MB/s`;
  return `${(n * 1000).toFixed(0)} KB/s`;
}

export function fmtBytes(value: unknown): string {
  const n = num(value);
  if (n === null) return '--';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = n;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** "3h 42m" style duration. */
export function fmtDuration(seconds: unknown): string {
  const n = num(seconds);
  if (n === null || n < 0) return '--';
  const total = Math.floor(n);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${total % 60}s`;
  return `${total}s`;
}

/** Relative age, e.g. "4m ago". */
export function timeAgo(iso: unknown): string {
  if (!iso) return 'never';
  const then = new Date(String(iso)).getTime();
  if (!Number.isFinite(then)) return 'unknown';
  const diff = Math.max(0, Date.now() - then);
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** "14:28" clock label. */
export function clockTime(iso: unknown): string {
  if (!iso) return '--:--';
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return '--:--';
  return d.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  });
}

/** "13:30" axis label. */
export function axisTime(iso: unknown): string {
  if (!iso) return '';
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  });
}

export function dateStamp(iso: unknown): string {
  if (!iso) return '--';
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return '--';
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  });
}

export function isoDay(iso: unknown): string {
  if (!iso) return '--';
  const d = new Date(String(iso));
  if (Number.isNaN(d.getTime())) return '--';
  return d.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/** Sentra's documented risk band for a 0-100 score. */
export function riskBand(score: unknown): {
  label: 'NORMAL' | 'ELEVATED' | 'HIGH' | 'CRITICAL';
  accent: Accent;
  badge: string;
} {
  const n = num(score);
  if (n === null) return { label: 'NORMAL', accent: 'green', badge: 'badge-normal' };
  if (n >= 85) return { label: 'CRITICAL', accent: 'red', badge: 'badge-high' };
  if (n >= 70) return { label: 'HIGH', accent: 'amber', badge: 'badge-elevated' };
  if (n >= 45) return { label: 'ELEVATED', accent: 'cyan', badge: 'badge-cyan' };
  return { label: 'NORMAL', accent: 'green', badge: 'badge-normal' };
}

/** Map a Sentra severity word onto accent + badge classes. */
export function severityStyle(severity: unknown): { accent: Accent; badge: string } {
  switch ( String(severity || '' ).toUpperCase() ) {
    case 'CRITICAL':
      return { accent: 'red', badge: 'badge-high' };
    case 'HIGH':
      return { accent: 'red', badge: 'badge-high' };
    case 'MEDIUM':
      return { accent: 'amber', badge: 'badge-elevated' };
    case 'LOW':
      return { accent: 'green', badge: 'badge-normal' };
    default:
      return { accent: 'cyan', badge: 'badge-cyan' };
  }
}

/** Alert status (OPEN / ACKNOWLEDGED / RESOLVED) -> badge. */
export function statusStyle(status: unknown): { accent: Accent; badge: string } {
  switch ( String(status || '' ).toUpperCase() ) {
    case 'OPEN':
    case 'NEW':
      return { accent: 'red', badge: 'badge-high' };
    case 'ACKNOWLEDGED':
    case 'REVIEW':
      return { accent: 'amber', badge: 'badge-elevated' };
    case 'RESOLVED':
    case 'CLOSED':
      return { accent: 'green', badge: 'badge-normal' };
    default:
      return { accent: 'cyan', badge: 'badge-cyan' };
  }
}

/**
 * A single percentage metric's badge, using Sentra's resource bands.
 * The spec asks for NORMAL below 70 and ELEVATED at/above it.
 */
export function usageBand(percent: unknown): { label: string; accent: Accent; badge: string } {
  const n = num(percent);
  if (n === null) return { label: 'NORMAL', accent: 'green', badge: 'badge-normal' };
  if (n >= 90) return { label: 'CRITICAL', accent: 'red', badge: 'badge-high' };
  if (n >= 70) return { label: 'ELEVATED', accent: 'amber', badge: 'badge-elevated' };
  return { label: 'NORMAL', accent: 'green', badge: 'badge-normal' };
}

/** CPU / memory / disk / net -> the 0-100 "System Health" style score. */
export function usageScore(percent: unknown): number | null {
  const n = num(percent);
  if (n === null) return null;
  return Math.max(0, Math.min(100, 100 - n));
}

/** Turn a backend metric key into a readable title. */
export function humanMetric(metric: unknown): string {
  const key = String(metric || '').trim();
  if (!key) return 'Unknown event';
  return key
    .replace(/_percent$/, '')
    .replace(/_mbs$/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function titleCase(value: unknown): string {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** A short, deterministic pseudo-random series for skeleton/sparkline chrome. */
export function sparkline(seed: number, length = 24): number[] {
  const out: number[] = [];
  let x = seed * 9301 + 49297;
  for (let i = 0; i < length; i += 1) {
    x = (x * 9301 + 49297) % 233280;
    out.push(0.35 + (x / 233280) * 0.5);
  }
  return out;
}

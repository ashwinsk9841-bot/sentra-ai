'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState, WindowSelect } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchLogs, WINDOWS } from '@/lib/api';
import type { LogRow } from '@/lib/types';
import { clockTime, dateStamp, fmtInt } from '@/lib/format';

const LEVELS = ['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'] as const;

const LEVEL_COLOR: Record<string, string> = {
  ERROR: '#FF4D5E',
  CRITICAL: '#FF4D5E',
  WARNING: '#FFB020',
  WARN: '#FFB020',
  INFO: '#00D9FF',
  DEBUG: '#8FA7C2',
};

export default function LogsPage() {
  const [rows, setRows] = useState<LogRow[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [timeWindow, setTimeWindow] = useState('24h');
  const [level, setLevel] = useState<string>('ALL');
  const [source, setSource] = useState<string>('ALL');
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (w: string) => {
    setLoading(true);
    try {
      const payload = await fetchLogs(w, 300);
      setRows(payload.logs);
      setSources(payload.sources);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(timeWindow);
  }, [load, timeWindow]);

  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        if (level !== 'ALL' && String(row.level).toUpperCase() !== level) return false;
        if (source !== 'ALL' && row.source !== source) return false;
        if (query && !String(row.message ?? '').toLowerCase().includes(query.toLowerCase()))
          return false;
        return true;
      }),
    [rows, level, source, query],
  );

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const row of rows) {
      const key = String(row.level ?? 'INFO').toUpperCase();
      out[key] = (out[key] ?? 0) + 1;
    }
    return out;
  }, [rows]);

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="LOGS"
        subtitle="Tailed log lines from explicitly listed sources on monitored devices."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search messages..."
              className="h-8 w-40 rounded-md border bg-[#040a14] px-2.5 text-[11px] text-ink outline-none placeholder:text-muted/70"
              style={{ borderColor: 'rgba(0,217,255,0.2)' }}
            />
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              className="h-8 rounded-md border bg-[#040a14] px-2 text-[10.5px] text-ink"
              style={{ borderColor: 'rgba(0,217,255,0.2)' }}
            >
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="h-8 rounded-md border bg-[#040a14] px-2 text-[10.5px] text-ink"
              style={{ borderColor: 'rgba(0,217,255,0.2)' }}
            >
              <option value="ALL">ALL SOURCES</option>
              {sources.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      <div className="mb-3 flex flex-wrap gap-2">
        {Object.entries(counts).map(([key, value]) => (
          <span
            key={key}
            className="badge"
            style={{
              color: LEVEL_COLOR[key] ?? '#8FA7C2',
              background: `${LEVEL_COLOR[key] ?? '#8FA7C2'}14`,
            }}
          >
            {key} {fmtInt(value)}
          </span>
        ))}
      </div>

      <Panel title="Log Stream" bodyClassName="px-2 pb-2">
        {loading ? (
          <LoadingBlock rows={1} height={320} />
        ) : filtered.length === 0 ? (
          <EmptyState message="No log lines match the current filters" />
        ) : (
          <div className="max-h-[600px] overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Level</th>
                  <th>Source</th>
                  <th>Message</th>
                  <th className="text-right">Count</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => {
                  const color = LEVEL_COLOR[String(row.level).toUpperCase()] ?? '#8FA7C2';
                  return (
                    <tr key={row.id}>
                      <td className="tabular whitespace-nowrap text-[10px] text-muted">
                        {clockTime(row.ts)}
                        <span className="ml-1 text-muted/60">{dateStamp(row.ts).slice(0, 6)}</span>
                      </td>
                      <td>
                        <span className="badge" style={{ color, background: `${color}14` }}>
                          {String(row.level ?? '').toUpperCase()}
                        </span>
                      </td>
                      <td className="whitespace-nowrap text-[10.5px] text-cyan/80">
                        {row.source ?? '--'}
                      </td>
                      <td className="font-mono text-[10.5px] text-ink/90">{row.message ?? '--'}</td>
                      <td className="tabular text-right text-muted">
                        {fmtInt(row.occurrences ?? 1)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

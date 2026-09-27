'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchProcesses } from '@/lib/api';
import type { ProcessRow } from '@/lib/types';
import { fmt, fmtInt, num, timeAgo, usageBand } from '@/lib/format';

export default function ProcessesPage() {
  const [rows, setRows] = useState<ProcessRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<keyof ProcessRow>('cpu_percent');
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchProcesses(150);
      setRows(payload.processes);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(() => {
    const filtered = query
      ? rows.filter((r) => `${r.name} ${r.owner ?? ''} ${r.pid}`.toLowerCase().includes(query.toLowerCase()))
      : rows;
    return [...filtered].sort((a, b) => (num(b[sortKey]) ?? -1) - (num(a[sortKey]) ?? -1));
  }, [rows, sortKey, query]);

  const totalRss = rows.reduce((acc, r) => acc + (num(r.rss_mb) ?? 0), 0);
  const totalThreads = rows.reduce((acc, r) => acc + (num(r.num_threads) ?? 0), 0);

  const header = (key: keyof ProcessRow, label: string, align?: 'right') => (
    <th
      className={align === 'right' ? 'cursor-pointer text-right' : 'cursor-pointer'}
      onClick={() => setSortKey(key)}
    >
      {label}
      {sortKey === key ? ' ↓' : ''}
    </th>
  );

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="PROCESSES"
        subtitle="Process snapshots reported by the Sentra agent. Aggregate identity and resource use only."
        action={
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter processes..."
              className="h-8 w-44 rounded-md border bg-[#040a14] px-2.5 text-[11px] text-ink outline-none placeholder:text-muted/70"
              style={{ borderColor: 'rgba(0,217,255,0.2)' }}
            />
            <button type="button" className="btn-neon" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Processes" value={fmtInt(rows.length)} />
        <Stat label="Resident Memory" value={`${fmt(totalRss, 0)} MB`} />
        <Stat label="Threads" value={fmtInt(totalThreads)} />
        <Stat label="Snapshot" value={rows[0] ? timeAgo(rows[0].ts) : '--'} />
      </div>

      <Panel title="Process Table" bodyClassName="px-2 pb-2">
        {loading ? (
          <LoadingBlock rows={1} height={280} />
        ) : sorted.length === 0 ? (
          <EmptyState message="No process snapshots reported" />
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  {header('pid', 'PID', 'right')}
                  <th>Name</th>
                  <th>Owner</th>
                  <th>Status</th>
                  {header('cpu_percent', 'CPU %', 'right')}
                  {header('memory_percent', 'MEM %', 'right')}
                  {header('rss_mb', 'RSS MB', 'right')}
                  {header('num_threads', 'Threads', 'right')}
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row) => {
                  const cpu = usageBand(row.cpu_percent);
                  return (
                    <tr key={row.id}>
                      <td className="tabular text-right text-muted">{row.pid}</td>
                      <td className="font-medium text-ink">{row.name}</td>
                      <td className="text-muted">{row.owner ?? '--'}</td>
                      <td>
                        <span className="badge badge-cyan">
                          {String(row.status ?? 'UNKNOWN').toUpperCase()}
                        </span>
                      </td>
                      <td className="tabular text-right">
                        <span style={{ color: cpu.accent === 'green' ? '#00E5A0' : '#FFB020' }}>
                          {fmt(row.cpu_percent, 2)}
                        </span>
                      </td>
                      <td className="tabular text-right text-ink">{fmt(row.memory_percent, 2)}</td>
                      <td className="tabular text-right text-muted">{fmt(row.rss_mb, 1)}</td>
                      <td className="tabular text-right text-muted">{fmtInt(row.num_threads)}</td>
                      <td className="whitespace-nowrap text-[10px] text-muted">
                        {timeAgo(row.create_time)}
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass-panel glass-panel-hover px-3.5 py-3">
      <div className="label-micro">{label}</div>
      <div className="metric-value mt-1 text-[18px]">{value}</div>
    </div>
  );
}

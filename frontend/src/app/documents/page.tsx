'use client';

import { useCallback, useEffect, useState } from 'react';
import { FileText, RefreshCw } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchDocuments } from '@/lib/api';
import type { DocumentRow } from '@/lib/types';
import { dateStamp, fmtBytes, fmtInt } from '@/lib/format';

const STATUS_BADGE: Record<string, string> = {
  INDEXED: 'badge-normal',
  FAILED: 'badge-high',
  PENDING: 'badge-cyan',
};

export default function DocumentsPage() {
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchDocuments();
      setRows(payload.documents);
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

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="DOCUMENTS"
        subtitle="Knowledge base sources available to the Sentra investigator."
        action={
          <button type="button" className="btn-neon" onClick={() => void load()}>
            <RefreshCw size={12} /> Refresh
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Panel title={`Documents (${rows.length})`} bodyClassName="px-2 pb-2">
        {loading ? (
          <LoadingBlock rows={1} height={280} />
        ) : rows.length === 0 ? (
          <EmptyState message="No documents ingested. Seed demo mode to add the runbook." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>File</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th className="text-right">Chunks</th>
                  <th className="text-right">Size</th>
                  <th className="text-right">Chars</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="font-medium text-ink">
                      <span className="flex items-center gap-1.5">
                        <FileText size={12} className="text-cyan/80" />
                        {row.title ?? row.filename ?? row.id.slice(0, 8)}
                      </span>
                    </td>
                    <td className="max-w-[220px] truncate text-[10.5px] text-muted">
                      {row.filename ?? '--'}
                    </td>
                    <td className="whitespace-nowrap text-[10.5px] text-cyan/80">
                      {row.source ?? '--'}
                    </td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[String(row.status).toUpperCase()] ?? 'badge-cyan'}`}>
                        {String(row.status ?? 'UNKNOWN').toUpperCase()}
                      </span>
                    </td>
                    <td className="tabular text-right text-ink">{fmtInt(row.chunk_count ?? 0)}</td>
                    <td className="tabular text-right text-muted">{fmtBytes(row.size_bytes)}</td>
                    <td className="tabular text-right text-muted">{fmtInt(row.char_count ?? 0)}</td>
                    <td className="tabular whitespace-nowrap text-[10px] text-muted">
                      {dateStamp(row.updated_at ?? row.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

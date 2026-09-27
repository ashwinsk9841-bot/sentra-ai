'use client';

import { useCallback, useEffect, useState } from 'react';
import { Database, Loader2, Search, Sparkles } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchRag, ragAnswer, ragRetrieve } from '@/lib/api';
import type { RagPayload } from '@/lib/types';
import { fmtInt, titleCase } from '@/lib/format';

interface Hit {
  label?: string;
  preview?: string;
  score?: number;
  document_id?: string;
}

export default function RagLabPage() {
  const [data, setData] = useState<RagPayload | null>(null);
  const [query, setQuery] = useState('cpu spike investigation');
  const [answer, setAnswer] = useState<string | null>(null);
  const [hits, setHits] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchRag());
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

  const run = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const [answerResult, retrieveResult] = await Promise.all([
        ragAnswer(query),
        ragRetrieve(query, 5),
      ]);
      setAnswer(
        String(
          answerResult.answer ??
            answerResult.text ??
            'The pipeline returned no answer for this query.',
        ),
      );
      const sources = (retrieveResult.sources ?? retrieveResult.hits ?? []) as Hit[];
      setHits(Array.isArray(sources) ? sources : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'RAG query failed');
    } finally {
      setBusy(false);
    }
  };

  const stats = (data?.stats ?? {}) as Record<string, unknown>;
  const usage = (data?.usage ?? {}) as Record<string, unknown>;

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="RAG LAB"
        subtitle="Query the Sentra vector store and inspect the retrieved evidence."
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Documents" value={fmtInt(Number(stats.documents ?? 0))} />
        <Stat label="Indexed" value={fmtInt(Number(stats.indexed ?? 0))} />
        <Stat label="Chunks" value={fmtInt(Number(stats.total_chunks ?? 0))} />
        <Stat
          label="Vector store"
          value={String((stats.vector_store as Record<string, unknown>)?.backend ?? '--')}
        />
        <Stat label="Queries" value={fmtInt(Number(usage.queries ?? 0))} />
        <Stat label="Avg latency" value={`${Number(usage.avg_latency_ms ?? 0).toFixed(0)} ms`} />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Panel title="Query">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <div className="relative flex-1">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-cyan/70" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask the knowledge base..."
                className="h-9 w-full rounded-lg border bg-[#040a14] pl-9 pr-3 text-[11.5px] text-ink outline-none placeholder:text-muted/70 focus:shadow-neon-cyan"
                style={{ borderColor: 'rgba(0,217,255,0.22)' }}
              />
            </div>
            <button type="submit" className="btn-neon" disabled={busy}>
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              Retrieve
            </button>
          </form>

          <div className="mt-3 min-h-[180px]">
            {loading ? (
              <LoadingBlock rows={1} height={160} />
            ) : answer ? (
              <div
                className="rounded-lg border px-3.5 py-3"
                style={{ borderColor: 'rgba(0,217,255,0.25)', background: 'rgba(0,217,255,0.05)' }}
              >
                <div className="label-micro mb-1.5">Answer</div>
                <p className="whitespace-pre-wrap text-[11.5px] leading-relaxed text-ink/90">
                  {answer}
                </p>
              </div>
            ) : (
              <p className="text-[11px] text-muted/80">
                Run a query to see a grounded answer and its supporting chunks.
              </p>
            )}
          </div>
        </Panel>

        <Panel title={`Retrieved Chunks (${hits.length})`}>
          {hits.length === 0 ? (
            <p className="text-[11px] text-muted/80">No retrieval has been run yet.</p>
          ) : (
            <div className="space-y-2">
              {hits.map((hit, i) => (
                <div
                  key={`${hit.document_id ?? 'doc'}-${i}`}
                  className="rounded-lg border px-3 py-2.5"
                  style={{ borderColor: 'rgba(0,217,255,0.14)', background: 'rgba(2,6,13,0.6)' }}
                >
                  <div className="flex items-center gap-2">
                    <Database size={11} className="text-cyan/80" />
                    <span className="truncate text-[10.5px] font-semibold text-ink">
                      {hit.label ?? `chunk ${i + 1}`}
                    </span>
                    <span className="tabular ml-auto text-[10.5px] font-bold text-cyan">
                      {Number(hit.score ?? 0).toFixed(3)}
                    </span>
                  </div>
                  <p className="mt-1.5 line-clamp-4 whitespace-pre-wrap text-[10px] leading-relaxed text-muted">
                    {hit.preview ?? ''}
                  </p>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {Array.isArray(data?.history) && data.history.length > 0 && (
        <div className="mt-3">
          <Panel title="Query History">
            <div className="max-h-[260px] overflow-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Query</th>
                    <th>Provider</th>
                    <th className="text-right">Hits</th>
                    <th className="text-right">Top score</th>
                    <th className="text-right">Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((row, i) => {
                    const r = row as Record<string, unknown>;
                    return (
                      <tr key={String(r.id ?? i)}>
                        <td className="max-w-[380px] truncate text-ink">{String(r.query ?? '')}</td>
                        <td className="text-cyan/80">{String(r.provider ?? '--')}</td>
                        <td className="tabular text-right text-muted">
                          {fmtInt(Number(r.hit_count ?? 0))}
                        </td>
                        <td className="tabular text-right text-muted">
                          {Number(r.top_score ?? 0).toFixed(3)}
                        </td>
                        <td className="tabular text-right text-muted">
                          {fmtInt(Number(r.latency_ms ?? 0))} ms
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}

      <p className="mt-3 text-[10px] text-muted/70">
        Embedding provider: {titleCase(String((stats.embedder as string) ?? 'local-hashing'))} &middot;
        chunk size {String(stats.chunk_size ?? '--')} &middot; top-k {String(stats.top_k ?? '--')}
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass-panel glass-panel-hover px-3.5 py-3">
      <div className="label-micro truncate">{label}</div>
      <div className="metric-value mt-1 truncate text-[16px]">{value}</div>
    </div>
  );
}

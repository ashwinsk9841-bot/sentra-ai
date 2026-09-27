'use client';

import { useCallback, useEffect, useState } from 'react';
import { Brain, Database, Loader2, Play, Sparkles, Trash2, Zap } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { clearDemo, dashboard, runCycle, seedDemo, trainModel } from '@/lib/api';
import type { DashboardPayload } from '@/lib/types';
import { fmtInt, titleCase } from '@/lib/format';

const SCENARIOS = [
  { id: 'anomaly', label: 'Anomaly burst' },
  { id: 'mixed', label: 'Mixed incidents' },
  { id: 'normal', label: 'Healthy baseline' },
  { id: 'quiet', label: 'Quiet' },
];

export default function SettingsPage() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scenario, setScenario] = useState('anomaly');
  const [samples, setSamples] = useState(240);

  const load = useCallback(async () => {
    try {
      setData(await dashboard('24h'));
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

  const run = async (key: string, fn: () => Promise<unknown>, message: string) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Operation failed');
    } finally {
      setBusy(null);
    }
  };

  const model = (data?.model ?? {}) as Record<string, unknown>;
  const demo = (data?.demo ?? {}) as Record<string, unknown>;

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="SETTINGS"
        subtitle="Detection control, model training and the demonstration dataset."
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}
      {notice && (
        <div
          className="mb-4 rounded-xl border px-4 py-2.5"
          style={{ borderColor: 'rgba(0,229,160,0.35)', background: 'rgba(0,229,160,0.07)' }}
        >
          <span className="text-[11.5px] font-semibold text-matrix">{notice}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel title="Detection Control">
          <div className="space-y-2.5">
            <Action
              icon={<Zap size={13} />}
              title="Run detection cycle"
              description="Collect telemetry now and score it against the trained ensemble."
              busy={busy === 'cycle'}
              onClick={() => void run('cycle', () => runCycle(), 'Detection cycle completed')}
            />
            <Action
              icon={<Brain size={13} />}
              title="Train anomaly model"
              description={
                model.trained
                  ? `Trained on ${fmtInt(Number(model.samples ?? 0))} samples with ${fmtInt(
                      Number(model.features ?? 0),
                    )} features.`
                  : 'No trained model detected yet.'
              }
              busy={busy === 'train'}
              onClick={() => void run('train', () => trainModel(), 'Model training completed')}
            />
          </div>

          <div className="mt-3 border-t border-cyan/10 pt-3">
            <div className="label-micro mb-1.5">Ensemble</div>
            <div className="flex flex-wrap gap-1.5">
              {(model.models as string[] | undefined)?.map((m) => (
                <span key={m} className="badge badge-cyan">
                  {m}
                </span>
              ))}
            </div>
            {model.message ? (
              <p className="mt-2 text-[10px] text-muted">{String(model.message)}</p>
            ) : null}
          </div>
        </Panel>

        <Panel title="Demo Dataset">
          <div className="space-y-3">
            <div>
              <div className="label-micro mb-1.5">Scenario</div>
              <div className="flex flex-wrap gap-1.5">
                {SCENARIOS.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`btn-ghost ${scenario === s.id ? 'nav-item-active' : ''}`}
                    onClick={() => setScenario(s.id)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="label-micro mb-1.5">Samples: {samples}</div>
              <input
                type="range"
                min={60}
                max={600}
                step={20}
                value={samples}
                onChange={(e) => setSamples(Number(e.target.value))}
                className="w-full accent-cyan"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-neon"
                disabled={busy !== null}
                onClick={() =>
                  void run(
                    'seed',
                    () => seedDemo({ samples, scenario }),
                    `Seeded ${samples} ${scenario} samples`,
                  )
                }
              >
                {busy === 'seed' ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                Seed Demo Data
              </button>
              <button
                type="button"
                className="btn-ghost"
                disabled={busy !== null}
                onClick={() => void run('clear', () => clearDemo(), 'Demo data cleared')}
              >
                {busy === 'clear' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                Clear Demo Data
              </button>
            </div>

            <div className="border-t border-cyan/10 pt-2.5 text-[10px] text-muted">
              <div className="flex justify-between">
                <span>Seeded</span>
                <span className="font-semibold text-ink">{String(demo.seeded ?? '--')}</span>
              </div>
              <div className="mt-1 flex justify-between">
                <span>Device</span>
                <span className="font-semibold text-ink">{String(demo.device_name ?? '--')}</span>
              </div>
              <div className="mt-1 flex justify-between">
                <span>Totals</span>
                <span className="font-semibold text-ink">
                  {Object.entries(data?.totals ?? {})
                    .filter(([k]) => ['system_metrics', 'anomalies', 'alerts'].includes(k))
                    .map(([k, v]) => `${titleCase(k)} ${fmtInt(Number(v))}`)
                    .join('  |  ')}
                </span>
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="Storage" className="lg:col-span-2">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StorageStat icon={<Database size={13} />} label="System metrics" value={fmtInt(data?.totals?.system_metrics ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Network metrics" value={fmtInt(data?.totals?.network_metrics ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Process snapshots" value={fmtInt(data?.totals?.process_snapshots ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Log lines" value={fmtInt(data?.totals?.logs ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Anomalies" value={fmtInt(data?.totals?.anomalies ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Alerts" value={fmtInt(data?.totals?.alerts ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="Risk events" value={fmtInt(data?.totals?.risk_events ?? 0)} />
            <StorageStat icon={<Database size={13} />} label="RAG queries" value={fmtInt(data?.totals?.rag_queries ?? 0)} />
          </div>
          {loading && <div className="mt-3"><LoadingBlock rows={1} height={60} /></div>}
        </Panel>
      </div>
    </div>
  );
}

function Action({
  icon,
  title,
  description,
  busy,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <div
      className="flex items-center gap-3 rounded-lg border px-3 py-2.5"
      style={{ borderColor: 'rgba(0,217,255,0.14)', background: 'rgba(2,6,13,0.6)' }}
    >
      <span className="text-cyan">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[11.5px] font-semibold text-ink">{title}</div>
        <div className="text-[9.5px] text-muted">{description}</div>
      </div>
      <button type="button" className="btn-ghost" disabled={busy} onClick={onClick}>
        {busy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        Run
      </button>
    </div>
  );
}

function StorageStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded-lg border px-3 py-2.5"
      style={{ borderColor: 'rgba(0,217,255,0.12)', background: 'rgba(2,5,10,0.5)' }}
    >
      <div className="flex items-center gap-1.5 text-muted">
        {icon}
        <span className="label-micro">{label}</span>
      </div>
      <div className="tabular mt-1 text-[15px] font-bold text-ink">{value}</div>
    </div>
  );
}

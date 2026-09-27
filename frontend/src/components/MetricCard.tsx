'use client';

import { useId } from 'react';
import { ACCENT_HEX, type Accent, num } from '@/lib/format';

interface MiniChartProps {
  data: (number | null)[];
  accent: Accent;
  height?: number;
  width?: number;
}

/**
 * A tiny neon sparkline. Rendered as raw SVG (no chart library) because metric
 * cards render seven of these at once.
 */
export function MiniChart({ data, accent, height = 30, width = 108 }: MiniChartProps) {
  const gradientId = useId();
  const stroke = ACCENT_HEX[accent];

  const points = data.filter((v) => v !== null && Number.isFinite(v)) as number[];
  if (points.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden>
        <line
          x1={0}
          y1={height - 3}
          x2={width}
          y2={height - 3}
          stroke="rgba(143,167,194,0.22)"
          strokeWidth={1}
          strokeDasharray="3 4"
        />
      </svg>
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const pad = 3;

  const coords = points.map((value, i) => {
    const x = i * step;
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });

  // Smooth the polyline with a light Catmull-Rom -> bezier conversion.
  let path = `M ${coords[0][0]} ${coords[0][1]}`;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const [x0, y0] = coords[i];
    const [x1, y1] = coords[i + 1];
    const mx = (x0 + x1) / 2;
    path += ` C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`;
  }

  const areaPath = `${path} L ${width} ${height} L 0 ${height} Z`;
  const last = coords[coords.length - 1];

  return (
    <svg width={width} height={height} aria-hidden style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.34" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
        <filter id={`${gradientId}-glow`} x="-40%" y="-60%" width="180%" height="260%">
          <feGaussianBlur stdDeviation="1.8" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        filter={`url(#${gradientId}-glow)`}
      />
      <circle cx={last[0]} cy={last[1]} r={2} fill={stroke} filter={`url(#${gradientId}-glow)`} />
    </svg>
  );
}

interface MetricCardProps {
  title: string;
  value: string;
  badge: string;
  badgeClass: string;
  accent: Accent;
  icon: React.ReactNode;
  series: (number | null)[];
  hint?: string;
}

/** One of the seven compact metric cards. */
export function MetricCard({
  title,
  value,
  badge,
  badgeClass,
  accent,
  icon,
  series,
  hint,
}: MetricCardProps) {
  const stroke = ACCENT_HEX[accent];

  return (
    <article
      data-audit="metric"
      data-audit-label={title}
      className="glass-panel glass-panel-hover relative overflow-hidden px-3.5 pb-2 pt-3"
      style={{ minHeight: 116 }}
    >
      {/* accent hairline */}
      <span
        className="absolute inset-x-0 top-0 h-[2px] opacity-70"
        style={{ background: `linear-gradient(90deg, transparent, ${stroke}, transparent)` }}
      />

      <div className="flex items-start gap-2">
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border"
          style={{
            borderColor: `${stroke}44`,
            background: `${stroke}12`,
            color: stroke,
            filter: `drop-shadow(0 0 6px ${stroke}55)`,
          }}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[10.5px] font-medium leading-tight text-muted">{title}</div>
          <div
            className="metric-value mt-1 text-[21px]"
            style={{ textShadow: `0 0 18px ${stroke}33` }}
          >
            {value}
          </div>
        </div>
      </div>

      <div className="mt-1.5 flex items-end justify-between gap-2">
        <div className="flex flex-col gap-1">
          <span className={`badge ${badgeClass}`}>{badge}</span>
          {hint && <span className="text-[9px] text-muted/80">{hint}</span>}
        </div>
        <MiniChart data={series.length ? series : []} accent={accent} />
      </div>
    </article>
  );
}

/** Extract the tail of a metric series for a sparkline. */
export function tail(values: (number | null)[] | undefined, length = 26): (number | null)[] {
  if (!values || values.length === 0) return [];
  const slice = values.slice(-length);
  return slice.map((v) => (num(v) === null ? null : (num(v) as number)));
}

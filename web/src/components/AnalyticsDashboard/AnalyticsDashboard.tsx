'use client';
import { useState, useEffect } from 'react';
import { useAnalytics } from '@/hooks/useAnalytics';
import type { AgentStat, ModelStat, DailyStat } from '@/types/analytics';

const BAR_COLORS = ['#60a5fa', '#f97316', '#22c55e', '#a855f7', '#eab308', '#ec4899'];

function CssBar({ value, max, colorIndex = 0 }: { value: number; max: number; colorIndex?: number }) {
  const pct   = max > 0 ? Math.round((value / max) * 100) : 0;
  const color = BAR_COLORS[colorIndex % BAR_COLORS.length];
  return (
    <div className="h-2 rounded-full bg-border-dim overflow-hidden flex-1 min-w-[60px]">
      <div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

function SectionHeader({ label }: { label: string }) {
  return <div className="text-[10px] font-bold tracking-widest text-text-faint uppercase mb-2.5">{label}</div>;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function downloadBlob(url: string, filename: string) {
  const resp = await fetch(url);
  const blob = await resp.blob();
  const link = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = link;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(link);
}

// F28 — export in-memory daily stats as CSV without hitting the API
function exportDailyCsv(daily: { date: string; count: number }[]) {
  const rows = ['date,count', ...daily.map(d => `${d.date},${d.count}`)].join('\n');
  const blob = new Blob([rows], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `daily-activity-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function AnalyticsDashboard() {
  const { data, loading, refetch } = useAnalytics();

  if (loading) {
    // F26 — proper skeleton instead of plain text
    return (
      <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6 animate-pulse">
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-surface-hover rounded-xl p-4 h-20" />
          ))}
        </div>
        <div className="bg-surface-hover rounded-xl h-40" />
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-surface-hover rounded-xl h-48" />
          <div className="bg-surface-hover rounded-xl h-48" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        {/* F26 — error banner with retry */}
        <div className="bg-red-900/30 border border-red-700/40 rounded-xl px-6 py-4 flex flex-col items-center gap-3 max-w-xs text-center">
          <div className="text-3xl">⚠</div>
          <p className="text-sm text-red-300 m-0">Failed to load analytics data.</p>
          <button onClick={refetch}
            className="border border-border-strong rounded-lg px-3.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:border-border-strong transition-colors">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { totals, by_agent, by_model, daily } = data;
  const maxAgentCount = Math.max(...by_agent.map((a) => a.count), 1);
  const maxModelCount = Math.max(...by_model.map((m) => m.count), 1);
  const maxDailyCount = Math.max(...daily.map((d) => d.count), 1);

  const totalsCards = [
    { label: 'Total Requests', value: totals.total_requests.toString(),          color: 'text-accent-blue-light' },
    { label: 'Total Cost',     value: `$${totals.total_cost_usd.toFixed(4)}`,   color: 'text-accent-purple' },
    { label: 'Avg Duration',   value: `${(totals.avg_duration_ms / 1000).toFixed(1)}s`, color: 'text-accent-green' },
    { label: 'Input Tokens',   value: totals.total_input_tokens.toLocaleString(), color: 'text-accent-orange' },
    { label: 'Output Tokens',  value: totals.total_output_tokens.toLocaleString(), color: 'text-accent-yellow' },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6 bg-surface-panel text-text-primary flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="m-0 text-base font-bold">Analytics</h2>
        <div className="flex gap-1.5">
          {['csv', 'json'].map(fmt => (
            <button key={fmt} onClick={() => downloadBlob(`${API_BASE}/analytics/export?format=${fmt}`, `analytics.${fmt}`)}
              className="bg-surface-card border border-border-strong rounded-lg px-3 py-1 text-[11px] text-text-secondary hover:text-text-primary transition-colors">
              ↓ {fmt.toUpperCase()}
            </button>
          ))}
          <button onClick={refetch}
            className="bg-surface-card border border-border-strong rounded-lg px-3 py-1 text-[11px] text-text-secondary hover:text-text-primary transition-colors">
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Totals row */}
      <div className="flex gap-4 flex-wrap">
        {totalsCards.map(({ label, value, color }) => (
          <div key={label} className="bg-surface-card border border-border-dim rounded-xl px-4 py-3 min-w-[120px]">
            <div className={`text-xl font-bold ${color}`}>{value}</div>
            <div className="text-[11px] text-text-faint mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* By Agent + By Model */}
      <div className="flex gap-4 flex-wrap">
        {[
          { title: 'By Agent', items: by_agent, keyF: (a: AgentStat) => a.agent,  countF: (a: AgentStat) => a.count,  max: maxAgentCount, offset: 0 },
          { title: 'By Model', items: by_model, keyF: (m: ModelStat) => m.model,  countF: (m: ModelStat) => m.count,  max: maxModelCount, offset: 2 },
        ].map(({ title, items, keyF, countF, max, offset }) => (
          <div key={title} className="flex-1 min-w-[220px] bg-surface-card border border-border-dim rounded-xl p-4">
            <SectionHeader label={title} />
            {items.length === 0 && <div className="text-xs text-text-faint">No data</div>}
            <div className="flex flex-col gap-2.5">
              {(items as (AgentStat | ModelStat)[]).map((item, i) => (
                <div key={keyF(item as never)}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-text-primary">{keyF(item as never)}</span>
                    <span className="text-text-muted">{countF(item as never)}</span>
                  </div>
                  <CssBar value={countF(item as never)} max={max} colorIndex={i + offset} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Daily Activity */}
      <div className="bg-surface-card border border-border-dim rounded-xl p-4">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-[10px] font-bold tracking-widest text-text-faint uppercase">Daily Activity</span>
          {/* F28 — client-side CSV from in-memory state; no extra network request */}
          {daily.length > 0 && (
            <button onClick={() => exportDailyCsv(daily)}
              className="text-[10px] text-text-faint hover:text-text-secondary transition-colors border border-border-dim rounded px-2 py-0.5">
              ↓ CSV
            </button>
          )}
        {daily.length === 0 && <div className="text-xs text-text-faint">No data</div>}
        <div className="flex flex-col gap-2">
          {daily.map((d: DailyStat, i: number) => (
            <div key={d.date} className="flex items-center gap-2.5">
              <span className="text-[11px] text-text-muted w-20 flex-shrink-0 font-mono">{d.date}</span>
              <CssBar value={d.count} max={maxDailyCount} colorIndex={i} />
              <span className="text-[11px] text-text-muted w-7 text-right">{d.count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* #18 Prompt performance heatmap */}
      <HeatmapSection />

      {/* #15 Cost forecast */}
      <CostForecastSection />
    </div>
  );
}

// ── Heatmap ───────────────────────────────────────────────────────────────────

interface HeatmapCell { dow: number; hour: number; count: number }

const DOW_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function HeatmapSection() {
  const [cells, setCells] = useState<HeatmapCell[]>([]);
  useEffect(() => {
    fetch(`${API_BASE}/analytics/heatmap?days=28`)
      .then(r => r.json())
      .then(d => setCells(d.cells ?? []))
      .catch(() => {});
  }, []);

  const maxCount = Math.max(...cells.map(c => c.count), 1);
  const getCell = (dow: number, hour: number) => cells.find(c => c.dow === dow && c.hour === hour);

  return (
    <div className="bg-surface-card border border-border-dim rounded-xl p-4 overflow-x-auto">
      <SectionHeader label="Request Heatmap (28d — by day & hour)" />
      {cells.length === 0 ? (
        <div className="text-xs text-text-faint">No data</div>
      ) : (
        <div className="flex flex-col gap-0.5 min-w-[600px]">
          {/* Hour labels */}
          <div className="flex ml-9 gap-0.5">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="w-5 text-[8px] text-text-ghost text-center">{h % 6 === 0 ? h : ''}</div>
            ))}
          </div>
          {Array.from({ length: 7 }, (_, dow) => (
            <div key={dow} className="flex items-center gap-0.5">
              <span className="text-[9px] text-text-ghost w-8 text-right pr-1">{DOW_LABELS[dow]}</span>
              {Array.from({ length: 24 }, (_, hour) => {
                const cell = getCell(dow + 1, hour);
                const intensity = cell ? Math.round((cell.count / maxCount) * 255) : 0;
                return (
                  <div
                    key={hour}
                    title={cell ? `${DOW_LABELS[dow]} ${hour}:00 — ${cell.count} req` : ''}
                    className="w-5 h-4 rounded-sm transition-colors"
                    style={{ backgroundColor: intensity > 0 ? `rgba(96, 165, 250, ${intensity / 255})` : 'rgba(30,41,59,0.5)' }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Cost forecast ─────────────────────────────────────────────────────────────

function CostForecastSection() {
  const [forecast, setForecast] = useState<{ daily_avg_usd: number; projected_30d_usd: number; basis_days: number } | null>(null);
  useEffect(() => {
    fetch(`${API_BASE}/analytics/cost-forecast?days=7`)
      .then(r => r.json())
      .then(d => setForecast(d))
      .catch(() => {});
  }, []);

  if (!forecast) return null;

  return (
    <div className="bg-surface-card border border-border-dim rounded-xl p-4">
      <SectionHeader label="Cost Forecast" />
      <div className="flex gap-4 flex-wrap">
        <div>
          <div className="text-xl font-bold text-accent-green">${forecast.daily_avg_usd.toFixed(4)}</div>
          <div className="text-[11px] text-text-faint">Daily avg ({forecast.basis_days}d basis)</div>
        </div>
        <div>
          <div className="text-xl font-bold text-accent-purple">${forecast.projected_30d_usd.toFixed(2)}</div>
          <div className="text-[11px] text-text-faint">Projected 30 days</div>
        </div>
      </div>
    </div>
  );
}

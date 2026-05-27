'use client';
import { useAnalytics } from '@/hooks/useAnalytics';
import type { AgentStat, ModelStat, DailyStat } from '@/types/analytics';

const BAR_COLORS = ['#60a5fa', '#f97316', '#22c55e', '#a855f7', '#eab308', '#ec4899'];

function CssBar({
  value,
  max,
  colorIndex = 0,
}: {
  value: number;
  max: number;
  colorIndex?: number;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const color = BAR_COLORS[colorIndex % BAR_COLORS.length];
  return (
    <div
      style={{
        height: 8,
        borderRadius: 4,
        background: '#1a1a2e',
        overflow: 'hidden',
        flex: 1,
        minWidth: 60,
      }}
    >
      <div
        style={{
          height: '100%',
          width: `${pct}%`,
          background: color,
          borderRadius: 4,
          transition: 'width 0.4s ease',
        }}
      />
    </div>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.1em',
        color: '#475569',
        textTransform: 'uppercase',
        marginBottom: 10,
      }}
    >
      {label}
    </div>
  );
}

export function AnalyticsDashboard() {
  const { data, loading, refetch } = useAnalytics();

  if (loading) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#475569',
          fontSize: 13,
        }}
      >
        Loading analytics…
      </div>
    );
  }

  if (!data) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          color: '#475569',
        }}
      >
        <div style={{ fontSize: 36 }}>📊</div>
        <p style={{ fontSize: 13, margin: 0 }}>No analytics data available.</p>
        <button
          onClick={refetch}
          style={{
            background: '#1e1e2e',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: '6px 14px',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const { totals, by_agent, by_model, daily } = data;
  const maxAgentCount = Math.max(...by_agent.map((a) => a.count), 1);
  const maxModelCount = Math.max(...by_model.map((m) => m.count), 1);
  const maxDailyCount = Math.max(...daily.map((d) => d.count), 1);

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: 24,
        background: '#050509',
        color: '#e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        gap: 24,
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
          Analytics
        </h2>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={async () => {
              const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/analytics/export?format=csv`);
              const blob = await resp.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url; a.download = 'analytics.csv'; a.click();
              URL.revokeObjectURL(url);
            }}
            style={{ background: '#1a1a2e', color: '#94a3b8', border: '1px solid #334155', borderRadius: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 11 }}
          >
            ↓ CSV
          </button>
          <button
            onClick={async () => {
              const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/analytics/export?format=json`);
              const blob = await resp.blob();
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url; a.download = 'analytics.json'; a.click();
              URL.revokeObjectURL(url);
            }}
            style={{ background: '#1a1a2e', color: '#94a3b8', border: '1px solid #334155', borderRadius: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 11 }}
          >
            ↓ JSON
          </button>
          <button
            onClick={refetch}
            style={{ background: '#1a1a2e', color: '#94a3b8', border: '1px solid #334155', borderRadius: 8, padding: '4px 12px', cursor: 'pointer', fontSize: 11 }}
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Totals row */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        {[
          { label: 'Total Requests', value: totals.total_requests.toString(), color: '#60a5fa' },
          {
            label: 'Total Cost',
            value: `$${totals.total_cost_usd.toFixed(4)}`,
            color: '#a855f7',
          },
          {
            label: 'Avg Duration',
            value: `${(totals.avg_duration_ms / 1000).toFixed(1)}s`,
            color: '#22c55e',
          },
          {
            label: 'Input Tokens',
            value: totals.total_input_tokens.toLocaleString(),
            color: '#f97316',
          },
          {
            label: 'Output Tokens',
            value: totals.total_output_tokens.toLocaleString(),
            color: '#eab308',
          },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            style={{
              background: '#0d0d1a',
              border: '1px solid #1a1a2e',
              borderRadius: 10,
              padding: '12px 18px',
              minWidth: 120,
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 3 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* By Agent + By Model */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {/* By Agent */}
        <div
          style={{
            flex: 1,
            minWidth: 220,
            background: '#0d0d1a',
            border: '1px solid #1a1a2e',
            borderRadius: 10,
            padding: 16,
          }}
        >
          <SectionHeader label="By Agent" />
          {by_agent.length === 0 && (
            <div style={{ fontSize: 12, color: '#475569' }}>No data</div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {by_agent.map((a: AgentStat, i: number) => (
              <div key={a.agent}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 12,
                    marginBottom: 4,
                    color: '#e2e8f0',
                  }}
                >
                  <span>{a.agent}</span>
                  <span style={{ color: '#64748b' }}>{a.count}</span>
                </div>
                <CssBar value={a.count} max={maxAgentCount} colorIndex={i} />
              </div>
            ))}
          </div>
        </div>

        {/* By Model */}
        <div
          style={{
            flex: 1,
            minWidth: 220,
            background: '#0d0d1a',
            border: '1px solid #1a1a2e',
            borderRadius: 10,
            padding: 16,
          }}
        >
          <SectionHeader label="By Model" />
          {by_model.length === 0 && (
            <div style={{ fontSize: 12, color: '#475569' }}>No data</div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {by_model.map((m: ModelStat, i: number) => (
              <div key={m.model}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 12,
                    marginBottom: 4,
                    color: '#e2e8f0',
                  }}
                >
                  <span>{m.model}</span>
                  <span style={{ color: '#64748b' }}>{m.count}</span>
                </div>
                <CssBar value={m.count} max={maxModelCount} colorIndex={i + 2} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Daily Activity */}
      <div
        style={{
          background: '#0d0d1a',
          border: '1px solid #1a1a2e',
          borderRadius: 10,
          padding: 16,
        }}
      >
        <SectionHeader label="Daily Activity" />
        {daily.length === 0 && (
          <div style={{ fontSize: 12, color: '#475569' }}>No data</div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {daily.map((d: DailyStat, i: number) => (
            <div key={d.date} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  fontSize: 11,
                  color: '#64748b',
                  width: 80,
                  flexShrink: 0,
                  fontFamily: 'monospace',
                }}
              >
                {d.date}
              </span>
              <CssBar value={d.count} max={maxDailyCount} colorIndex={i} />
              <span style={{ fontSize: 11, color: '#64748b', width: 30, textAlign: 'right' }}>
                {d.count}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

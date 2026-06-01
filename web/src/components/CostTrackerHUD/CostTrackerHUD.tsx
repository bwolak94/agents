'use client';
import { useState, useEffect } from 'react';
import { API_URL } from '@/constants/api';

interface CostData {
  total_cost_usd: number;
  total_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

interface Props {
  budgetUsd?: number;
}

export function CostTrackerHUD({ budgetUsd = 0 }: Props) {
  const [cost, setCost] = useState<CostData | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const load = () => {
      fetch(`${API_URL}/analytics?days=1`)
        .then(r => r.json())
        .then(d => {
          const t = d.totals ?? {};
          setCost({
            total_cost_usd: t.total_cost_usd ?? 0,
            total_requests: t.total_requests ?? 0,
            total_input_tokens: t.total_input_tokens ?? 0,
            total_output_tokens: t.total_output_tokens ?? 0,
          });
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!cost) return null;

  const pct = budgetUsd > 0 ? Math.min(100, (cost.total_cost_usd / budgetUsd) * 100) : -1;
  const warning = pct >= 80;
  const barColor = pct >= 90 ? '#dc2626' : pct >= 80 ? '#eab308' : '#22c55e';

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        zIndex: 1000,
        background: '#0f172a',
        border: `1px solid ${warning ? '#7f1d1d' : '#1e293b'}`,
        borderRadius: 10,
        padding: expanded ? '12px 16px' : '6px 12px',
        fontSize: 11,
        color: '#94a3b8',
        cursor: 'pointer',
        minWidth: 120,
        boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
        transition: 'all 0.2s',
      }}
      onClick={() => setExpanded(e => !e)}
      title="Today's cost tracker — click to expand"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: warning ? '#f87171' : '#4ade80', fontWeight: 700 }}>
          ${cost.total_cost_usd.toFixed(4)}
        </span>
        <span style={{ color: '#475569' }}>today</span>
        {pct >= 0 && (
          <span style={{ color: barColor, fontWeight: 600 }}>
            {pct.toFixed(0)}%
          </span>
        )}
      </div>

      {/* Budget progress bar */}
      {pct >= 0 && (
        <div style={{ height: 3, background: '#1e293b', borderRadius: 2, marginTop: 4, width: '100%' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: barColor, borderRadius: 2, transition: 'width 0.5s' }} />
        </div>
      )}

      {expanded && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid #1e293b', paddingTop: 8 }}>
          <Row label="Requests" value={cost.total_requests} />
          <Row label="Input tokens" value={cost.total_input_tokens.toLocaleString()} />
          <Row label="Output tokens" value={cost.total_output_tokens.toLocaleString()} />
          {budgetUsd > 0 && <Row label="Budget" value={`$${budgetUsd.toFixed(2)}`} />}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
      <span style={{ color: '#475569' }}>{label}</span>
      <span style={{ color: '#cbd5e1', fontWeight: 600 }}>{value}</span>
    </div>
  );
}

'use client';
import { useState, useEffect, useRef } from 'react';
import { API_URL, WS_URL } from '@/constants/api';

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
  const [showSession, setShowSession] = useState(false);  // F19 — toggle daily vs. session cost
  const sessionCostRef = useRef(0);  // #47 — accumulate per-session cost from WS events
  const warnedRef = useRef(false);  // F29 — fire toast only once per session
  const [budgetToast, setBudgetToast] = useState<string | null>(null);  // F29

  useEffect(() => {
    // #47 — initial fetch for today's baseline; then WS cost events keep it live
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

    // #47 — listen for cost events from the existing WS stream
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout>;
    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string);
          if (msg.type === 'cost' && typeof msg.usd === 'number') {
            sessionCostRef.current += msg.usd;  // F19 — accumulate session-scoped cost
            setCost(prev => prev ? {
              ...prev,
              total_cost_usd: prev.total_cost_usd + msg.usd,
              total_requests: prev.total_requests + 1,
            } : prev);
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => { retryTimer = setTimeout(connect, 5000); };
      ws.onerror = () => ws?.close();
    };
    connect();
    // Fallback: re-fetch every 5 min in case WS misses events
    const id = setInterval(load, 300_000);
    return () => {
      clearInterval(id);
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  // F29 — fire one-shot toast when budget crosses 80%
  useEffect(() => {
    if (!cost || budgetUsd <= 0 || warnedRef.current) return;
    const pct = (cost.total_cost_usd / budgetUsd) * 100;
    if (pct >= 80) {
      warnedRef.current = true;
      setBudgetToast(`Budget alert: ${pct.toFixed(0)}% of $${budgetUsd.toFixed(2)} used`);
      setTimeout(() => setBudgetToast(null), 6000);
    }
  }, [cost, budgetUsd]);

  if (!cost) return null;

  // F19 — display session cost or daily cost depending on toggle
  const displayCost = showSession ? sessionCostRef.current : cost.total_cost_usd;
  const pct = budgetUsd > 0 ? Math.min(100, (cost.total_cost_usd / budgetUsd) * 100) : -1;
  const warning = pct >= 80;
  const barColor = pct >= 90 ? '#dc2626' : pct >= 80 ? '#eab308' : '#22c55e';

  return (
    <>
      {/* F29 — budget warning toast */}
      {budgetToast && (
        <div style={{
          position: 'fixed', bottom: 72, right: 16, zIndex: 1001,
          background: '#7f1d1d', border: '1px solid #dc2626', borderRadius: 8,
          padding: '8px 14px', fontSize: 12, color: '#fca5a5',
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)', maxWidth: 260,
          animation: 'fadeIn 0.2s ease',
        }}>
          ⚠ {budgetToast}
        </div>
      )}
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
          ${displayCost.toFixed(4)}
        </span>
        {/* F19 — toggle between daily and session cost */}
        <span
          onClick={e => { e.stopPropagation(); setShowSession(s => !s); }}
          style={{ color: '#475569', cursor: 'pointer', fontSize: 10, userSelect: 'none' }}
          title="Click to toggle session / daily cost"
        >
          {showSession ? 'session' : 'today'}
        </span>
        {pct >= 0 && !showSession && (
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
    </>
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

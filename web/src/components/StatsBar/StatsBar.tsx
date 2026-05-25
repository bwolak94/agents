import type { CSSProperties } from 'react';
import type { Stats, Costs } from '@/types/chat';

interface StatBoxProps {
  label: string;
  value: string | number;
  color: string;
  flash?: boolean;
}

function StatBox({ label, value, color, flash = false }: StatBoxProps) {
  const containerStyle: CSSProperties = {
    background: '#0d0d1a',
    border: `1px solid ${color}44`,
    borderRadius: 4,
    padding: '8px 14px',
    textAlign: 'center',
  };

  return (
    <div style={containerStyle}>
      <div
        className={flash ? 'counter-pop' : ''}
        style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 16, color, marginBottom: 4 }}
      >
        {value}
      </div>
      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 6, color: color + '88' }}>
        {label}
      </div>
    </div>
  );
}

interface StatsBarProps {
  stats: Stats;
  costs: Costs | null;
}

export function StatsBar({ stats, costs }: StatsBarProps) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        padding: '8px 12px',
        background: '#050509',
        borderBottom: '1px solid #1a1a2e',
        flexWrap: 'wrap',
      }}
    >
      <StatBox label="ACTIVE" value={stats.active} color="#f97316" />
      <StatBox label="COMPLETED" value={stats.completed} color="#22c55e" flash={stats.completedFlash} />
      <StatBox label="TOTAL" value={stats.total} color="#60a5fa" />
      <StatBox label="ROUTING" value={stats.routing} color="#dc2626" />
      {costs?.total_cost_usd !== undefined && (
        <StatBox label="COST $USD" value={`$${costs.total_cost_usd.toFixed(4)}`} color="#a855f7" />
      )}
      {costs?.cache_read_tokens && costs.cache_read_tokens > 0 ? (
        <StatBox
          label="CACHED"
          value={`${(costs.cache_read_tokens / 1000).toFixed(1)}K`}
          color="#eab308"
        />
      ) : null}
    </div>
  );
}

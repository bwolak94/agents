import type { Stats, Costs } from '@/types/chat';
import styles from './StatsBar.module.css';

interface StatBoxProps {
  label: string;
  value: string | number;
  color: string;
  flash?: boolean;
}

function StatBox({ label, value, color, flash = false }: StatBoxProps) {
  return (
    <div className={styles.box} style={{ border: `1px solid ${color}44` }}>
      <div
        className={`${styles.value}${flash ? ' counter-pop' : ''}`}
        style={{ color }}
      >
        {value}
      </div>
      <div className={styles.label} style={{ color: color + '88' }}>
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
    <div className={styles.bar}>
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

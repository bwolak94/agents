import type { Agent } from '@/types/agent';
import type { AppEvent } from '@/types/event';
import type { Stats, Costs } from '@/types/chat';
import type { WsStatus } from '@/hooks/useWebSocket';
import { ZONES } from '@/constants/zones';
import { GAME_CSS } from '@/constants/gameStyles';
import { StatsBar } from '@/components/StatsBar/StatsBar';
import { ZoneCell } from '@/components/ZoneCell/ZoneCell';
import { EventLog } from '@/components/EventLog/EventLog';
import styles from './WorldView.module.css';

interface WorldViewProps {
  agents: Record<string, Agent>;
  stats: Stats;
  costs: Costs | null;
  events: AppEvent[];
  wsStatus: WsStatus;
}

const WS_STATUS_CONFIG: Record<WsStatus, { color: string; label: string }> = {
  connected: { color: '#22c55e', label: 'LIVE' },
  connecting: { color: '#eab308', label: 'CONNECTING' },
  offline: { color: '#dc2626', label: 'OFFLINE' },
};

export function WorldView({ agents, stats, costs, events, wsStatus }: WorldViewProps) {
  const agentList = Object.values(agents);
  const { color: statusColor, label: statusLabel } = WS_STATUS_CONFIG[wsStatus];

  return (
    <div className={styles.root}>
      <div className="crt-overlay" />
      <style>{GAME_CSS}</style>

      <div className={styles.header}>
        <div className={styles.title}>AGENT WORLD</div>
        <div className={styles.statusRow}>
          <div
            className={styles.statusDot}
            style={{ background: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
          />
          <span className={styles.statusLabel} style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </div>
      </div>

      <StatsBar stats={stats} costs={costs} />

      <div className={styles.grid}>
        <div className={styles.gridInner}>
          {ZONES.map((zone) => (
            <ZoneCell key={zone.id} zone={zone} agents={agentList} />
          ))}
        </div>
      </div>

      <EventLog events={events} />
    </div>
  );
}

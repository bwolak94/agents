import type { Agent } from '@/types/agent';
import type { AppEvent } from '@/types/event';
import type { Stats, Costs } from '@/types/chat';
import type { WsStatus } from '@/hooks/useWebSocket';
import { ZONES } from '@/constants/zones';
import { GAME_CSS } from '@/constants/gameStyles';
import { StatsBar } from '@/components/StatsBar/StatsBar';
import { ZoneCell } from '@/components/ZoneCell/ZoneCell';
import { EventLog } from '@/components/EventLog/EventLog';

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
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: '#050509',
        position: 'relative',
      }}
    >
      <div className="crt-overlay" />
      <style>{GAME_CSS}</style>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 12px',
          background: '#0a0a1a',
          borderBottom: '1px solid #1a1a2e',
        }}
      >
        <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 10, color: '#7c3aed' }}>
          AGENT WORLD
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: statusColor,
              boxShadow: `0 0 6px ${statusColor}`,
            }}
          />
          <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 6, color: statusColor }}>
            {statusLabel}
          </span>
        </div>
      </div>

      <StatsBar stats={stats} costs={costs} />

      <div style={{ flex: 1, overflow: 'auto', padding: 10 }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gridTemplateRows: 'auto auto auto',
            gap: 8,
            minHeight: '100%',
          }}
        >
          {ZONES.map((zone) => (
            <ZoneCell key={zone.id} zone={zone} agents={agentList} />
          ))}
        </div>
      </div>

      <EventLog events={events} />
    </div>
  );
}

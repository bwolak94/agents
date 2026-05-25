import type { Stats, Costs } from '@/types/chat';
import type { WsStatus } from '@/hooks/useWebSocket';

export type ViewId = 'chat' | 'analytics';

interface HeaderProps {
  wsStatus: WsStatus;
  stats: Stats;
  costs: Costs | null;
  view: ViewId;
  onViewChange: (view: ViewId) => void;
}

const WS_STATUS_CONFIG: Record<WsStatus, { color: string; label: string }> = {
  connected: { color: '#22c55e', label: 'Live' },
  connecting: { color: '#eab308', label: 'Connecting' },
  offline: { color: '#dc2626', label: 'Offline' },
};

const NAV_TABS: { id: ViewId; icon: string; label: string }[] = [
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'analytics', icon: '📊', label: 'Analytics' },
];

interface StatPillProps {
  label: string;
  value: string | number;
  color: string;
}

function StatPill({ label, value, color }: StatPillProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ fontSize: 12, color, fontWeight: 700 }}>{value}</span>
      <span style={{ fontSize: 11, color: '#475569' }}>{label}</span>
    </div>
  );
}

export function Header({ wsStatus, stats, costs, view, onViewChange }: HeaderProps) {
  const { color: dotColor, label: wsLabel } = WS_STATUS_CONFIG[wsStatus];

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '0 20px',
        height: 48,
        background: '#050509',
        borderBottom: '1px solid #1a1a2e',
        flexShrink: 0,
        gap: 24,
      }}
    >
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 18 }}>🤖</span>
        <span style={{ fontWeight: 700, fontSize: 14, color: '#e2e8f0' }}>Agent System</span>
        <span style={{ fontSize: 11, color: '#334155' }}>Claude · Gemini · Ollama</span>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: '#1a1a2e' }} />

      {/* Nav tabs */}
      <nav style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {NAV_TABS.map((tab) => {
          const isActive = view === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onViewChange(tab.id)}
              style={{
                background: isActive ? '#1a1a2e' : 'none',
                border: isActive ? '1px solid #334155' : '1px solid transparent',
                borderRadius: 8,
                color: isActive ? '#e2e8f0' : '#64748b',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                fontSize: 12,
                fontWeight: isActive ? 600 : 400,
                padding: '4px 10px',
                transition: 'all 0.15s',
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: '#1a1a2e' }} />

      {/* Stats */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <StatPill label="active" value={stats.active} color="#f97316" />
        <StatPill label="done" value={stats.completed} color="#22c55e" />
        <StatPill label="total" value={stats.total} color="#60a5fa" />
        {costs?.total_cost_usd !== undefined && (
          <StatPill label="cost" value={`$${costs.total_cost_usd.toFixed(4)}`} color="#a855f7" />
        )}
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* WS Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: `0 0 6px ${dotColor}`,
          }}
        />
        <span style={{ fontSize: 11, color: dotColor }}>{wsLabel}</span>
      </div>
    </header>
  );
}

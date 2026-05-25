import type { CSSProperties } from 'react';
import type { WsStatus } from '@/hooks/useWebSocket';

export type ViewId = 'world' | 'chat';

interface NavTabProps {
  id: ViewId;
  label: string;
  icon: string;
  activeView: ViewId;
  onClick: (id: ViewId) => void;
}

function NavTab({ id, label, icon, activeView, onClick }: NavTabProps) {
  const isActive = activeView === id;

  const style: CSSProperties = {
    background: isActive ? '#1e1e2e' : 'transparent',
    color: isActive ? '#e2e8f0' : '#475569',
    border: 'none',
    borderBottom: isActive ? '2px solid #7c3aed' : '2px solid transparent',
    padding: '10px 18px',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
    transition: 'all 0.2s',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  };

  return (
    <button onClick={() => onClick(id)} style={style}>
      {icon} {label}
    </button>
  );
}

interface HeaderProps {
  view: ViewId;
  onViewChange: (id: ViewId) => void;
  wsStatus: WsStatus;
  activeAgentCount: number;
}

const WS_DOT_COLOR: Record<WsStatus, string> = {
  connected: '#22c55e',
  connecting: '#eab308',
  offline: '#dc2626',
};

const NAV_TABS = [
  { id: 'world' as ViewId, icon: '🎮', label: 'World' },
  { id: 'chat' as ViewId, icon: '💬', label: 'Chat' },
];

export function Header({ view, onViewChange, wsStatus, activeAgentCount }: HeaderProps) {
  const dotColor = WS_DOT_COLOR[wsStatus];

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        background: '#050509',
        borderBottom: '1px solid #1a1a2e',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 20 }}>🤖</span>
        <span style={{ fontWeight: 700, fontSize: 15 }}>Agent System</span>
        <span style={{ fontSize: 12, color: '#475569' }}>Claude · Gemini · Ollama</span>
      </div>

      <div style={{ display: 'flex' }}>
        {NAV_TABS.map((tab) => (
          <NavTab key={tab.id} {...tab} activeView={view} onClick={onViewChange} />
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {activeAgentCount > 0 && (
          <div
            style={{
              fontFamily: "'Press Start 2P', monospace",
              fontSize: 8,
              color: '#f97316',
              background: '#1a0a00',
              padding: '4px 8px',
              borderRadius: 4,
              border: '1px solid #f9731644',
            }}
          >
            {activeAgentCount} AGENT{activeAgentCount !== 1 ? 'S' : ''} ACTIVE
          </div>
        )}
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: `0 0 8px ${dotColor}`,
          }}
        />
      </div>
    </div>
  );
}

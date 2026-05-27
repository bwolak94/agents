import type { AgentMap } from '@/types/agent';
import { AgentCard } from '@/components/AgentCard/AgentCard';

interface AgentPanelProps {
  agents: AgentMap;
}

export function AgentPanel({ agents }: AgentPanelProps) {
  const agentList = Object.values(agents).filter((a) => a.status !== 'fading');
  const count = agentList.length;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#050509',
      }}
    >
      {/* Panel header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #1a1a2e',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Active Agents
        </span>
        {count > 0 && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: '#f97316',
              background: '#f9731618',
              padding: '2px 8px',
              borderRadius: 10,
            }}
          >
            {count}
          </span>
        )}
      </div>

      {/* Agent cards */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
        {count === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              gap: 8,
              color: '#334155',
            }}
          >
            <span style={{ fontSize: 28 }}>💤</span>
            <span style={{ fontSize: 12 }}>System idle</span>
            <span style={{ fontSize: 11, color: '#1e293b' }}>Waiting for tasks...</span>
          </div>
        ) : (
          agentList.map((agent) => <AgentCard key={agent.id} agent={agent} />)
        )}
      </div>
    </div>
  );
}

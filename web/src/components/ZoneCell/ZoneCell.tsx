import type { CSSProperties } from 'react';
import type { Agent } from '@/types/agent';
import type { Zone } from '@/constants/zones';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';
import { AgentSprite } from '@/components/AgentSprite/AgentSprite';

interface ZoneCellProps {
  zone: Zone;
  agents: Agent[];
}

function getZoneAgents(agents: Agent[], zoneId: string): Agent[] {
  return agents.filter((agent) => {
    const cfg = AGENT_CFG[agent.type] ?? DEFAULT_AGENT_CFG;
    return cfg.zone === zoneId || (zoneId === 'dispatch' && agent.status === 'routing');
  });
}

export function ZoneCell({ zone, agents }: ZoneCellProps) {
  const zoneAgents = getZoneAgents(agents, zone.id);
  const isActive = zoneAgents.length > 0;

  const containerStyle: CSSProperties = {
    gridColumn: zone.col,
    gridRow: zone.row,
    background: zone.bg,
    border: `2px solid ${isActive ? zone.color : zone.color + '44'}`,
    borderRadius: 4,
    padding: 10,
    minHeight: zone.row === 1 ? 90 : 130,
    display: 'flex',
    flexDirection: 'column',
    transition: 'border-color 0.4s ease',
  };

  const labelStyle: CSSProperties = {
    fontFamily: "'Press Start 2P', monospace",
    fontSize: 7,
    color: isActive ? zone.color : zone.color + '88',
    letterSpacing: 1,
    transition: 'color 0.3s',
  };

  const badgeStyle: CSSProperties = {
    marginLeft: 'auto',
    fontFamily: "'Press Start 2P', monospace",
    fontSize: 7,
    color: zone.color,
    background: zone.color + '22',
    padding: '2px 5px',
    borderRadius: 2,
  };

  const emptyStyle: CSSProperties = {
    fontFamily: "'Press Start 2P', monospace",
    fontSize: 6,
    color: zone.color + '33',
    alignSelf: 'center',
    margin: 'auto',
  };

  return (
    <div className={`zone-cell ${isActive ? 'zone-active' : ''}`} style={containerStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 14 }}>{zone.icon}</span>
        <span style={labelStyle}>{zone.label}</span>
        {isActive && <span style={badgeStyle}>{zoneAgents.length} ACTIVE</span>}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', flex: 1 }}>
        {zoneAgents.map((agent) => (
          <AgentSprite key={agent.id} agent={agent} />
        ))}
        {!isActive && <div style={emptyStyle}>EMPTY</div>}
      </div>
    </div>
  );
}

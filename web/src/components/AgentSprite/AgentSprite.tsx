import type { CSSProperties } from 'react';
import type { Agent } from '@/types/agent';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';
import { SpeechBubble } from '@/components/SpeechBubble/SpeechBubble';

interface AgentSpriteProps {
  agent: Agent;
}

const STATUS_LABELS: Record<string, string> = {
  thinking: 'THINKING',
  done: 'DONE!',
  routing: 'ROUTING...',
};

function getAnimClass(status: Agent['status']): string {
  if (status === 'thinking' || status === 'using_tool') return 'think';
  if (status === 'done') return 'done';
  if (status === 'fading') return 'fade';
  return 'walk';
}

function getStatusLabel(agent: Agent): string {
  if (agent.status === 'using_tool') return `TOOL: ${agent.tool ?? '...'}`;
  return STATUS_LABELS[agent.status] ?? 'IDLE';
}

const THINKING_DOT_COLORS = [0, 1, 2];

export function AgentSprite({ agent }: AgentSpriteProps) {
  const cfg = AGENT_CFG[agent.type] ?? DEFAULT_AGENT_CFG;
  const animClass = getAnimClass(agent.status);
  const isWorking = agent.status === 'thinking' || agent.status === 'using_tool';
  const showBubble = Boolean(agent.task) && agent.status !== 'done' && agent.status !== 'fading';

  const labelStyle: CSSProperties = {
    fontFamily: "'Press Start 2P', monospace",
    fontSize: 5,
    color: cfg.color,
    marginTop: 2,
    textAlign: 'center',
    maxWidth: 60,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  };

  const dotStyle = (index: number): CSSProperties => ({
    width: 4,
    height: 4,
    borderRadius: '50%',
    background: cfg.color,
    animation: `dotBounce 1.2s ease-in-out ${index * 0.15}s infinite`,
  });

  return (
    <div
      style={{
        position: 'relative',
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        margin: '4px 6px',
      }}
    >
      {showBubble && <SpeechBubble text={agent.task!} color={cfg.color} />}
      <div
        className={`${animClass} spawn`}
        style={{ fontSize: 28, cursor: 'default', userSelect: 'none' }}
      >
        {cfg.icon}
      </div>
      <div style={labelStyle}>{getStatusLabel(agent)}</div>
      {isWorking && (
        <div style={{ display: 'flex', gap: 2, marginTop: 3 }}>
          {THINKING_DOT_COLORS.map((i) => (
            <div key={i} style={dotStyle(i)} />
          ))}
        </div>
      )}
    </div>
  );
}

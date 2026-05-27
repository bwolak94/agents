'use client';
import { useState, useEffect } from 'react';
import type { Agent } from '@/types/agent';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';

interface AgentCardProps {
  agent: Agent;
}

function useElapsedSeconds(startedAt?: number, active = true): number {
  const [elapsed, setElapsed] = useState(
    startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0,
  );

  useEffect(() => {
    if (!active || !startedAt) return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startedAt, active]);

  return elapsed;
}

function ProgressBar({ status, color }: { status: Agent['status']; color: string }) {
  const isWorking = status === 'thinking' || status === 'using_tool';
  const isRouting = status === 'routing' || status === 'idle';
  const isDone = status === 'done' || status === 'fading';

  const barStyle = {
    height: 3,
    borderRadius: 2,
    background: isDone ? '#22c55e' : color,
    width: isDone ? '100%' : isWorking ? '60%' : '30%',
    transition: 'width 0.4s ease',
  };

  const barClass = isWorking ? 'progress-shimmer' : isRouting ? 'progress-pulse' : '';

  return (
    <div style={{ height: 3, background: '#1a1a2e', borderRadius: 2, marginBottom: 8 }}>
      <div className={barClass} style={barStyle} />
    </div>
  );
}

function StatusLabel({ agent, color }: { agent: Agent; color: string }) {
  const label = (() => {
    if (agent.status === 'thinking') return 'Thinking...';
    if (agent.status === 'using_tool') return `Tool: ${agent.tool ?? '...'}`;
    if (agent.status === 'routing') return 'Routing...';
    if (agent.status === 'done') return 'Done';
    return 'Starting...';
  })();

  return (
    <span style={{ fontSize: 11, color, opacity: 0.85 }}>{label}</span>
  );
}

export function AgentCard({ agent }: AgentCardProps) {
  const cfg = AGENT_CFG[agent.type] ?? DEFAULT_AGENT_CFG;
  const isActive = agent.status !== 'done' && agent.status !== 'fading';
  const elapsed = useElapsedSeconds(agent.startedAt, isActive);

  return (
    <div
      className="agent-card-enter"
      style={{
        background: '#0d0d1a',
        border: `1px solid ${cfg.color}33`,
        borderLeft: `3px solid ${cfg.color}`,
        borderRadius: 6,
        padding: '12px 14px',
        marginBottom: 8,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{cfg.icon}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: cfg.color }}>{cfg.label}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {agent.model && (
            <span style={{ fontSize: 10, color: '#475569', background: '#1a1a2e', padding: '2px 6px', borderRadius: 4 }}>
              {agent.model}
            </span>
          )}
          <span style={{ fontSize: 11, color: '#64748b', fontVariantNumeric: 'tabular-nums' }}>
            {elapsed}s
          </span>
        </div>
      </div>

      {/* Task text */}
      {agent.task && (
        <p style={{
          fontSize: 12,
          color: '#94a3b8',
          margin: '0 0 8px',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {agent.task}
        </p>
      )}

      <ProgressBar status={agent.status} color={cfg.color} />

      <StatusLabel agent={agent} color={cfg.color} />
    </div>
  );
}

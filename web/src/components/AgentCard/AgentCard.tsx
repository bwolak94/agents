'use client';
import { useState, useEffect } from 'react';
import type { Agent } from '@/types/agent';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';

interface AgentCardProps {
  agent: Agent;
}

function useElapsedSeconds(startedAt?: number, active = true): number {
  const [elapsed, setElapsed] = useState(startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0);
  useEffect(() => {
    if (!active || !startedAt) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(id);
  }, [startedAt, active]);
  return elapsed;
}

function ProgressBar({ status, color }: { status: Agent['status']; color: string }) {
  const isWorking = status === 'thinking' || status === 'using_tool';
  const isRouting = status === 'routing' || status === 'idle';
  const isDone    = status === 'done'    || status === 'fading';

  return (
    <div className="h-[3px] bg-border-dim rounded-full mb-2 overflow-hidden">
      <div
        className={isWorking ? 'progress-shimmer' : isRouting ? 'progress-pulse' : ''}
        style={{
          height: '100%',
          borderRadius: 2,
          background: isDone ? '#22c55e' : color,
          width: isDone ? '100%' : isWorking ? '60%' : '30%',
          transition: 'width 0.4s ease',
        }}
      />
    </div>
  );
}

function statusLabel(agent: Agent): string {
  if (agent.status === 'thinking')   return 'Thinking...';
  if (agent.status === 'using_tool') return `Tool: ${agent.tool ?? '...'}`;
  if (agent.status === 'routing')    return 'Routing...';
  if (agent.status === 'done')       return 'Done';
  return 'Starting...';
}

export function AgentCard({ agent }: AgentCardProps) {
  const cfg     = AGENT_CFG[agent.type] ?? DEFAULT_AGENT_CFG;
  const isActive = agent.status !== 'done' && agent.status !== 'fading';
  const elapsed  = useElapsedSeconds(agent.startedAt, isActive);

  return (
    <div
      className="agent-card-enter rounded-md p-3 mb-2 border"
      style={{ borderColor: `${cfg.color}33`, borderLeftColor: cfg.color, borderLeftWidth: 3 }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-base">{cfg.icon}</span>
          <span className="text-xs font-semibold" style={{ color: cfg.color }}>{cfg.label}</span>
        </div>
        <div className="flex items-center gap-2">
          {/* #29 — model as styled badge pill */}
          {agent.model && (
            <span className="text-[10px] text-text-faint bg-border-dim px-1.5 py-0.5 rounded-full">
              {agent.model}
            </span>
          )}
          <span className="text-[11px] text-text-muted tabular-nums">{elapsed}s</span>
        </div>
      </div>

      {agent.task && (
        <p className="text-xs text-text-secondary mb-2 truncate">{agent.task}</p>
      )}

      <ProgressBar status={agent.status} color={cfg.color} />

      <span className="text-[11px] opacity-85" style={{ color: cfg.color }}>
        {statusLabel(agent)}
      </span>
    </div>
  );
}

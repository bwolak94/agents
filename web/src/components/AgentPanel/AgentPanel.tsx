'use client';
import { useState, useMemo, useEffect } from 'react';
import type { AgentMap } from '@/types/agent';
import { AgentCard } from '@/components/AgentCard/AgentCard';

interface AgentPanelProps {
  agents: AgentMap;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function AgentPanel({ agents, collapsed = false, onToggleCollapse }: AgentPanelProps) {
  const [filter, setFilter] = useState('');
  const [debouncedFilter, setDebouncedFilter] = useState('');
  const allAgents = Object.values(agents).filter((a) => a.status !== 'fading');

  // FE16 — Debounce the filter input (150ms) so re-renders only fire after typing stops
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedFilter(filter), 150);
    return () => clearTimeout(timer);
  }, [filter]);

  const agentList = useMemo(() => {
    if (!debouncedFilter.trim()) return allAgents;
    const q = debouncedFilter.toLowerCase();
    return allAgents.filter(
      (a) => a.id?.toLowerCase().includes(q) || a.status?.toLowerCase().includes(q)
    );
  }, [allAgents, debouncedFilter]);
  const count = allAgents.length;

  if (collapsed) {
    return (
      <div className="w-8 flex-shrink-0 border-r border-border-dim bg-surface-panel flex flex-col items-center pt-3 gap-2">
        {/* #20 — collapsed pill shows badge + expand button */}
        {count > 0 && (
          <span className="text-[10px] font-bold text-accent-orange bg-orange-950 rounded-full px-1.5 py-0.5 counter-pop">
            {count}
          </span>
        )}
        <button
          onClick={onToggleCollapse}
          title="Expand agent panel"
          aria-label="Expand agent panel"
          className="text-text-ghost hover:text-text-muted transition-colors text-lg"
        >
          ›
        </button>
      </div>
    );
  }

  return (
    <div className="w-[280px] flex-shrink-0 border-r border-border-dim bg-surface-panel flex flex-col overflow-hidden">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-border-dim flex items-center justify-between flex-shrink-0">
        <span className="text-[11px] font-semibold text-text-muted uppercase tracking-widest">
          Active Agents
        </span>
        <div className="flex items-center gap-2">
          {count > 0 && (
            <span className="text-[11px] font-bold text-accent-orange bg-orange-950/50 px-2 py-0.5 rounded-full counter-pop">
              {count}
            </span>
          )}
          {/* #20 — collapse button */}
          {onToggleCollapse && (
            <button
              onClick={onToggleCollapse}
              title="Collapse agent panel"
              aria-label="Collapse agent panel"
              className="text-text-ghost hover:text-text-muted transition-colors text-base leading-none"
            >
              ‹
            </button>
          )}
        </div>
      </div>

      {/* Live filter input */}
      {count > 0 && (
        <div className="px-3 py-1.5 border-b border-border-dim flex-shrink-0">
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Filter agents…"
            className="w-full bg-surface-hover border border-border-base rounded text-text-primary text-[10px] px-2 py-0.5 outline-none focus:border-border-strong transition-colors"
          />
        </div>
      )}

      {/* Agent cards */}
      <div className="flex-1 overflow-y-auto p-3">
        {count === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-border-strong">
            <span className="text-3xl">💤</span>
            <span className="text-xs">System idle</span>
            <span className="text-[11px] text-surface-active">Waiting for tasks...</span>
          </div>
        ) : (
          agentList.map((agent) => <AgentCard key={agent.id} agent={agent} />)
        )}
      </div>
    </div>
  );
}

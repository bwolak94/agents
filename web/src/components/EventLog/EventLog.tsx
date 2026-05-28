'use client';
import type { AppEvent } from '@/types/event';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';

interface EventLogProps {
  events: AppEvent[];
  collapsed: boolean;
  onToggle: () => void;
}

interface EventMeta { label: string; color: string; bg: string; }

const EVENT_META: Record<string, EventMeta> = {
  routing:        { label: 'ROUTING', color: '#dc2626', bg: 'bg-red-950/40'    },
  agent_start:    { label: 'SPAWN',   color: '#3b82f6', bg: 'bg-blue-950/40'   },
  agent_thinking: { label: 'THINK',   color: '#a855f7', bg: 'bg-purple-950/40' },
  agent_tools:    { label: 'TOOL',    color: '#eab308', bg: 'bg-yellow-950/40' },
  agent_done:     { label: 'DONE',    color: '#22c55e', bg: 'bg-green-950/40'  },
};

const MAX_EVENTS = 60;

function getAgentIcon(agentId?: string): string {
  if (!agentId) return '—';
  const type = agentId.replace(/-\d+$/, '');
  return (AGENT_CFG[type] ?? DEFAULT_AGENT_CFG).icon;
}

/**
 * #19 — Collapsible drawer instead of a fixed-height bottom strip.
 * Toggled by the parent via `collapsed` / `onToggle` props.
 */
export function EventLog({ events, collapsed, onToggle }: EventLogProps) {
  const displayed = [...events].reverse().slice(0, MAX_EVENTS);

  return (
    <div className={`flex-shrink-0 bg-surface-panel border-t border-border-dim transition-all duration-200 ${collapsed ? 'h-8' : 'h-44'}`}>
      {/* Drawer handle / header */}
      <button
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="w-full flex items-center gap-2 px-4 py-1.5 text-left hover:bg-surface-hover transition-colors group"
      >
        <span className="text-[11px] font-semibold text-text-ghost uppercase tracking-widest">
          Timeline
        </span>
        {events.length > 0 && (
          <span className="text-[10px] text-border-base">{events.length} events</span>
        )}
        <div className="flex-1" />
        <span className="text-text-ghost group-hover:text-text-faint transition-colors text-xs">
          {collapsed ? '▲' : '▼'}
        </span>
      </button>

      {!collapsed && (
        <div className="overflow-y-auto h-[calc(100%-28px)]">
          {displayed.length === 0 ? (
            <div className="px-4 py-3 text-[11px] text-border-base">No events yet...</div>
          ) : (
            displayed.map((ev) => {
              const meta = EVENT_META[ev.type] ?? { label: ev.type.toUpperCase(), color: '#475569', bg: 'bg-surface-active' };
              const icon = getAgentIcon(ev.agent_id);
              return (
                <div
                  key={ev.id}
                  className="event-slide flex items-center gap-2.5 px-4 py-0.5 border-b border-[#0a0a14] text-[11px]"
                >
                  <span className="text-[10px] text-border-base min-w-[58px] tabular-nums">{ev.time}</span>
                  <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded min-w-[56px] text-center ${meta.bg}`} style={{ color: meta.color }}>
                    {meta.label}
                  </span>
                  <span className="min-w-[20px]">{icon}</span>
                  <span className="text-text-ghost min-w-[90px] truncate">{ev.agent_id ?? '—'}</span>
                  {ev.detail && (
                    <span className="text-border-strong truncate flex-1">{ev.detail}</span>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

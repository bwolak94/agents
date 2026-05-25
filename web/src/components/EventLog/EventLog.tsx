import type { AppEvent } from '@/types/event';
import { AGENT_CFG, DEFAULT_AGENT_CFG } from '@/constants/agents';

interface EventLogProps {
  events: AppEvent[];
}

interface EventMeta {
  label: string;
  color: string;
  bg: string;
}

const EVENT_META: Record<string, EventMeta> = {
  routing:        { label: 'ROUTING', color: '#dc2626', bg: '#dc262618' },
  agent_start:    { label: 'SPAWN',   color: '#3b82f6', bg: '#3b82f618' },
  agent_thinking: { label: 'THINK',   color: '#a855f7', bg: '#a855f718' },
  agent_tools:    { label: 'TOOL',    color: '#eab308', bg: '#eab30818' },
  agent_done:     { label: 'DONE',    color: '#22c55e', bg: '#22c55e18' },
};

const MAX_EVENTS = 60;

function getAgentIcon(agentId?: string): string {
  if (!agentId) return '—';
  const type = agentId.replace(/-\d+$/, '');
  return (AGENT_CFG[type] ?? DEFAULT_AGENT_CFG).icon;
}

export function EventLog({ events }: EventLogProps) {
  const displayed = [...events].reverse().slice(0, MAX_EVENTS);

  return (
    <div
      style={{
        height: 180,
        display: 'flex',
        flexDirection: 'column',
        background: '#050509',
        borderTop: '1px solid #1a1a2e',
      }}
    >
      {/* Timeline header */}
      <div
        style={{
          padding: '6px 16px',
          borderBottom: '1px solid #0f1117',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, color: '#334155', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Timeline
        </span>
        <span style={{ fontSize: 10, color: '#1e293b' }}>{events.length} events</span>
      </div>

      {/* Events */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {displayed.length === 0 ? (
          <div style={{ padding: '12px 16px', fontSize: 11, color: '#1e293b' }}>
            No events yet...
          </div>
        ) : (
          displayed.map((ev) => {
            const meta = EVENT_META[ev.type] ?? { label: ev.type.toUpperCase(), color: '#475569', bg: '#47556918' };
            const icon = getAgentIcon(ev.agent_id);

            return (
              <div
                key={ev.id}
                className="event-slide"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '3px 16px',
                  borderBottom: '1px solid #0a0a14',
                }}
              >
                {/* Time */}
                <span style={{ fontSize: 10, color: '#1e293b', minWidth: 58, fontVariantNumeric: 'tabular-nums' }}>
                  {ev.time}
                </span>

                {/* Badge */}
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    color: meta.color,
                    background: meta.bg,
                    padding: '1px 6px',
                    borderRadius: 4,
                    minWidth: 56,
                    textAlign: 'center',
                    letterSpacing: '0.04em',
                  }}
                >
                  {meta.label}
                </span>

                {/* Agent */}
                <span style={{ fontSize: 11, color: '#334155', minWidth: 20 }}>{icon}</span>
                <span style={{ fontSize: 11, color: '#475569', minWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {ev.agent_id ?? '—'}
                </span>

                {/* Detail */}
                {ev.detail && (
                  <span style={{ fontSize: 11, color: '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                    {ev.detail}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

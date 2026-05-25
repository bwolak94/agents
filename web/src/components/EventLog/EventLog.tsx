import type { CSSProperties } from 'react';
import type { AppEvent } from '@/types/event';

interface EventLogProps {
  events: AppEvent[];
}

const TYPE_COLOR: Record<string, string> = {
  routing: '#dc2626',
  agent_start: '#3b82f6',
  agent_thinking: '#a855f7',
  agent_tools: '#eab308',
  agent_done: '#22c55e',
};

const TYPE_LABEL: Record<string, string> = {
  routing: 'ROUTING',
  agent_start: 'SPAWN',
  agent_thinking: 'THINK',
  agent_tools: 'TOOLS',
  agent_done: 'DONE',
};

const MAX_DISPLAYED_EVENTS = 30;

const PIXEL_FONT: CSSProperties = { fontFamily: "'Press Start 2P', monospace" };

export function EventLog({ events }: EventLogProps) {
  const displayedEvents = [...events].reverse().slice(0, MAX_DISPLAYED_EVENTS);

  return (
    <div
      style={{
        height: 140,
        overflowY: 'auto',
        background: '#050509',
        borderTop: '1px solid #1a1a2e',
        padding: '6px 10px',
      }}
    >
      <div style={{ ...PIXEL_FONT, fontSize: 6, color: '#334155', marginBottom: 6 }}>EVENT LOG</div>
      {displayedEvents.map((ev) => {
        const color = TYPE_COLOR[ev.type] ?? '#475569';
        const label = TYPE_LABEL[ev.type] ?? ev.type.toUpperCase();
        return (
          <div
            key={ev.id}
            className="event-slide"
            style={{ display: 'flex', gap: 8, marginBottom: 3, alignItems: 'center' }}
          >
            <span style={{ ...PIXEL_FONT, fontSize: 5, color: '#334155', minWidth: 50 }}>
              {ev.time}
            </span>
            <span
              style={{
                ...PIXEL_FONT,
                fontSize: 5,
                color,
                background: color + '22',
                padding: '1px 4px',
                borderRadius: 2,
                minWidth: 52,
              }}
            >
              {label}
            </span>
            <span style={{ ...PIXEL_FONT, fontSize: 5, color: '#64748b' }}>
              [{ev.agent_id ?? '—'}]
            </span>
            {ev.detail && (
              <span
                style={{
                  ...PIXEL_FONT,
                  fontSize: 5,
                  color: '#475569',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {ev.detail}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

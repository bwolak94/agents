'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { Agent, AgentMap } from '@/types/agent';
import type { AppEvent } from '@/types/event';
import type { Stats, Costs } from '@/types/chat';
import type { WsEvent } from '@/types/ws';
import { API_URL, WS_URL } from '@/constants/api';

export type WsStatus = 'connecting' | 'connected' | 'offline';

interface UseWebSocketResult {
  agents: AgentMap;
  events: AppEvent[];
  wsStatus: WsStatus;
  costs: Costs | null;
  stats: Stats;
  clearAgents: () => void;
}

const AGENT_FADE_DELAY_MS = 2000;
const AGENT_REMOVE_DELAY_MS = 600;
const WS_RETRY_DELAY_MS = 3000;
const STATS_FLASH_DURATION_MS = 400;
const MAX_EVENTS = 100;

const INITIAL_STATS: Stats = {
  active: 0,
  completed: 0,
  total: 0,
  routing: 0,
  completedFlash: false,
};

export function useWebSocket(sessionId: string | null): UseWebSocketResult {
  const [agents, setAgents] = useState<AgentMap>({});
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [wsStatus, setWsStatus] = useState<WsStatus>('connecting');
  const [costs, setCosts] = useState<Costs | null>(null);
  const [stats, setStats] = useState<Stats>(INITIAL_STATS);
  const eventIdRef = useRef(0);

  const addEvent = useCallback((ev: Omit<AppEvent, 'id' | 'time'>) => {
    const time = new Date().toTimeString().slice(0, 8);
    setEvents((prev) => [
      ...prev.slice(-(MAX_EVENTS - 1)),
      { ...ev, id: eventIdRef.current++, time },
    ]);
  }, []);

  // #14 — debounced cost fetch: with parallel agents, agent_done fires multiple times
  const fetchCostsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchCosts = useCallback(() => {
    if (!sessionId) return;
    if (fetchCostsDebounceRef.current) clearTimeout(fetchCostsDebounceRef.current);
    fetchCostsDebounceRef.current = setTimeout(() => {
      fetch(`${API_URL}/stats?session_id=${sessionId}`)
        .then((r) => r.json())
        .then((d: { costs?: Costs }) => {
          if (d.costs) setCosts(d.costs);
        })
        .catch(() => {});
    }, 500);
  }, [sessionId]);

  const handleMessage = useCallback(
    (ev: WsEvent) => {
      if (ev.type === 'ping') return;

      const detail = (() => {
        if ('task' in ev && ev.task) return ev.task;
        if ('tools' in ev && ev.tools) return ev.tools.join(', ');
        if ('duration_ms' in ev && ev.duration_ms) return `${ev.duration_ms}ms`;
        return undefined;
      })();

      addEvent({
        type: ev.type,
        agent_id: 'agent_id' in ev ? ev.agent_id : undefined,
        detail,
      });

      switch (ev.type) {
        case 'routing':
          setStats((s) => ({ ...s, routing: s.routing + 1, total: s.total + 1 }));
          setAgents((prev) => ({
            ...prev,
            [ev.agent_id]: {
              id: ev.agent_id,
              type: 'general_agent',
              status: 'routing',
              task: ev.task,
            },
          }));
          break;

        case 'agent_start':
          setStats((s) => ({ ...s, active: s.active + 1 }));
          setAgents((prev) => ({
            ...prev,
            [ev.agent_id]: {
              id: ev.agent_id,
              type: ev.agent_type,
              model: ev.model,
              task: ev.task,
              status: 'idle',
              tools: ev.tools,
              startedAt: Date.now(),
            },
          }));
          break;

        case 'agent_thinking':
          setAgents((prev) =>
            prev[ev.agent_id]
              ? { ...prev, [ev.agent_id]: { ...prev[ev.agent_id], status: 'thinking' } }
              : prev,
          );
          break;

        case 'agent_tools':
          setAgents((prev) =>
            prev[ev.agent_id]
              ? {
                  ...prev,
                  [ev.agent_id]: {
                    ...prev[ev.agent_id],
                    status: 'using_tool',
                    tool: ev.tools?.[0],
                  },
                }
              : prev,
          );
          break;

        case 'agent_done': {
          const agentId = ev.agent_id;
          setStats((s) => ({
            ...s,
            active: Math.max(0, s.active - 1),
            completed: s.completed + 1,
            completedFlash: true,
          }));
          setTimeout(
            () => setStats((s) => ({ ...s, completedFlash: false })),
            STATS_FLASH_DURATION_MS,
          );

          setAgents((prev) =>
            prev[agentId] ? { ...prev, [agentId]: { ...prev[agentId], status: 'done' } } : prev,
          );

          setTimeout(() => {
            setAgents((prev) => {
              if (!prev[agentId]) return prev;
              return { ...prev, [agentId]: { ...prev[agentId], status: 'fading' } };
            });
            setTimeout(() => {
              setAgents((prev) => {
                const next = { ...prev };
                delete next[agentId];
                return next;
              });
            }, AGENT_REMOVE_DELAY_MS);
          }, AGENT_FADE_DELAY_MS);

          fetchCosts();
          break;
        }
      }
    },
    [addEvent, fetchCosts],
  );

  useEffect(() => {
    let ws: WebSocket;
    let retryTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      setWsStatus('connecting');
      const wsUrl = sessionId ? `${WS_URL}?session_id=${sessionId}` : WS_URL;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => setWsStatus('connected');
      ws.onclose = () => {
        setWsStatus('offline');
        retryTimer = setTimeout(connect, WS_RETRY_DELAY_MS);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e: MessageEvent<string>) => {
        handleMessage(JSON.parse(e.data) as WsEvent);
      };
    };

    connect();
    return () => {
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [handleMessage, sessionId]);

  const clearAgents = useCallback(() => {
    setAgents({});
    setEvents([]);
  }, []);

  return { agents, events, wsStatus, costs, stats, clearAgents };
}

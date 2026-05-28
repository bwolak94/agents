"use client";

export const dynamic = "force-dynamic";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AgentEvent {
  type: string;
  session_id?: string;
  agent?: string;
  model?: string;
  tools?: string[];
  node?: string;
  run_id?: string;
  ts?: string;
}

interface ModelHealth {
  [model: string]: string;
}

interface CollabEdge {
  caller: string;
  callee: string;
  count: number;
}

interface AnalyticsTotals {
  total_requests: number;
  total_cost_usd: number;
  avg_duration_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

const EVENT_COLORS: Record<string, string> = {
  react_step:             "#6366f1",
  tool_call:              "#f59e0b",
  agent_done:             "#22c55e",
  workflow_node_start:    "#8b5cf6",
  workflow_node_complete: "#22c55e",
  workflow_node_error:    "#ef4444",
  waiting_for_human:      "#f59e0b",
};

export default function MonitorPage() {
  const [events, setEvents]       = useState<AgentEvent[]>([]);
  const [health, setHealth]       = useState<ModelHealth>({});
  const [collab, setCollab]       = useState<CollabEdge[]>([]);
  const [metrics, setMetrics]     = useState<AnalyticsTotals | null>(null);  // #16
  const [connected, setConnected] = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      try {
        const wsUrl = API_URL.replace(/^http/, "ws") + "/ws";
        const socket = new WebSocket(wsUrl);

        socket.onopen = () => {
          if (!cancelled) setConnected(true);
        };
        socket.onclose = () => {
          if (!cancelled) {
            setConnected(false);
            timerRef.current = setTimeout(connect, 3000);
          }
        };
        socket.onerror = () => {
          if (!cancelled) setConnected(false);
        };
        socket.onmessage = (e: MessageEvent) => {
          if (cancelled) return;
          try {
            const ev = JSON.parse(e.data as string) as AgentEvent;
            if (ev.type === "ping") return;
            setEvents(prev =>
              [{ ...ev, ts: new Date().toLocaleTimeString() }, ...prev].slice(0, 100)
            );
          } catch {
            // ignore malformed messages
          }
        };
        wsRef.current = socket;
      } catch (err) {
        if (!cancelled) setConnected(false);
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const [hRes, cRes, aRes] = await Promise.all([
          fetch(`${API_URL}/models/health`),
          fetch(`${API_URL}/agents/collab-graph`),
          fetch(`${API_URL}/analytics/summary`),      // #16
        ]);
        if (cancelled) return;
        if (hRes.ok) {
          const h = await hRes.json() as { health?: ModelHealth };
          setHealth(h.health ?? {});
        }
        if (cRes.ok) {
          const c = await cRes.json() as { summary?: CollabEdge[] };
          setCollab(c.summary ?? []);
        }
        if (aRes.ok) {
          const a = await aRes.json() as { totals?: AnalyticsTotals };
          setMetrics(a.totals ?? null);
        }
        setError(null);
      } catch (e) {
        if (!cancelled) setError("Cannot reach API at " + API_URL);
      }
    }

    poll();
    const id = setInterval(poll, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div style={{ fontFamily: "system-ui,sans-serif", background: "#0f172a", minHeight: "100vh", color: "#f1f5f9", padding: "1.5rem" }}>
      {/* Header */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700 }}>Agent Monitor</h1>
          <p style={{ margin: "0.25rem 0 0", color: "#94a3b8", fontSize: "0.875rem" }}>
            Real-time agent activity dashboard — {API_URL}
          </p>
        </div>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: "0.5rem",
          padding: "0.375rem 0.75rem", borderRadius: "9999px",
          background: connected ? "#14532d" : "#7f1d1d",
          color:      connected ? "#86efac" : "#fca5a5",
          fontSize: "0.8125rem", fontWeight: 500,
        }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
          {connected ? "Live" : "Reconnecting…"}
        </span>
      </header>

      {/* API error banner */}
      {error && (
        <div style={{ background: "#7f1d1d", color: "#fca5a5", padding: "0.75rem 1rem", borderRadius: "0.5rem", marginBottom: "1rem", fontSize: "0.875rem" }}>
          {error}
        </div>
      )}

      {/* #16 Live Metrics Panel */}
      {metrics && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.75rem", marginBottom: "1rem" }}>
          {[
            { label: "Total Requests", value: metrics.total_requests.toLocaleString() },
            { label: "Total Cost",     value: `$${metrics.total_cost_usd.toFixed(4)}` },
            { label: "Avg Latency",    value: `${Math.round(metrics.avg_duration_ms)}ms` },
            { label: "Input Tokens",   value: metrics.total_input_tokens.toLocaleString() },
            { label: "Output Tokens",  value: metrics.total_output_tokens.toLocaleString() },
          ].map(({ label, value }) => (
            <div key={label} style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "0.875rem 1rem" }}>
              <p style={{ margin: 0, color: "#94a3b8", fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</p>
              <p style={{ margin: "0.25rem 0 0", fontSize: "1.25rem", fontWeight: 700, color: "#f1f5f9" }}>{value}</p>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "1rem", marginBottom: "1rem" }}>
        {/* Model Health */}
        <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "1rem" }}>
          <h2 style={sectionTitle}>Model Health</h2>
          {Object.keys(health).length === 0
            ? <p style={{ color: "#94a3b8", fontSize: "0.875rem", margin: 0 }}>No models detected</p>
            : Object.entries(health).map(([model, status]) => (
                <div key={model} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.375rem 0", borderBottom: "1px solid #0f172a" }}>
                  <span style={{ fontSize: "0.875rem" }}>{model}</span>
                  <span style={{
                    padding: "0.125rem 0.5rem", borderRadius: "9999px", fontSize: "0.75rem", fontWeight: 500,
                    background: status === "healthy" ? "#14532d" : "#7f1d1d",
                    color:      status === "healthy" ? "#86efac" : "#fca5a5",
                  }}>
                    {status}
                  </span>
                </div>
              ))
          }
        </div>

        {/* Collab Graph */}
        <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "1rem" }}>
          <h2 style={sectionTitle}>Agent Collaboration</h2>
          {collab.length === 0
            ? <p style={{ color: "#94a3b8", fontSize: "0.875rem", margin: 0 }}>No delegations recorded yet</p>
            : collab.slice(0, 8).map((edge, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.375rem 0", fontSize: "0.8125rem", borderBottom: "1px solid #0f172a" }}>
                  <span>
                    <span style={{ color: "#a5b4fc" }}>{edge.caller}</span>
                    <span style={{ color: "#94a3b8", margin: "0 0.375rem" }}>→</span>
                    <span style={{ color: "#86efac" }}>{edge.callee}</span>
                  </span>
                  <span style={{ color: "#94a3b8" }}>{edge.count}×</span>
                </div>
              ))
          }
        </div>
      </div>

      {/* Live Events */}
      <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "0.75rem", padding: "1rem" }}>
        <h2 style={sectionTitle}>
          Live Events{" "}
          <span style={{ color: "#6366f1", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>({events.length})</span>
        </h2>
        <div style={{ maxHeight: "26rem", overflowY: "auto", fontFamily: "monospace", fontSize: "0.8125rem" }}>
          {events.length === 0 && (
            <p style={{ color: "#94a3b8", margin: 0 }}>Waiting for events… Send a chat message to see activity.</p>
          )}
          {events.map((ev, i) => {
            const color = EVENT_COLORS[ev.type] ?? "#94a3b8";
            const tools = Array.isArray(ev.tools) ? ev.tools : [];
            return (
              <div key={i} style={{ padding: "0.375rem 0.5rem", borderBottom: "1px solid #0f172a", display: "flex", gap: "0.75rem", alignItems: "flex-start" }}>
                <span style={{ color: "#475569", flexShrink: 0, minWidth: 70 }}>{ev.ts ?? ""}</span>
                <span style={{
                  padding: "0.0625rem 0.375rem", borderRadius: "0.25rem", fontSize: "0.75rem", flexShrink: 0,
                  background: color + "33", color,
                }}>
                  {ev.type}
                </span>
                <span style={{ color: "#cbd5e1", wordBreak: "break-all" }}>
                  {ev.session_id && <span style={{ color: "#6366f1" }}>[{ev.session_id}] </span>}
                  {ev.agent     && <span>{ev.agent} </span>}
                  {ev.model     && <span style={{ color: "#94a3b8" }}>via {ev.model} </span>}
                  {ev.node      && <span style={{ color: "#8b5cf6" }}>node:{ev.node} </span>}
                  {ev.run_id    && <span style={{ color: "#94a3b8" }}>run:{ev.run_id.slice(0, 8)} </span>}
                  {tools.length > 0 && <span style={{ color: "#f59e0b" }}>tools:[{tools.join(",")}]</span>}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const sectionTitle: CSSProperties = {
  margin: "0 0 0.75rem",
  fontSize: "0.75rem",
  fontWeight: 600,
  color: "#94a3b8",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

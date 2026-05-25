"use client";
import { useState, useRef, useEffect, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_URL  = API_URL.replace(/^http/, "ws") + "/ws";

// ─── Agent & zone config ──────────────────────────────────────────────────────

const AGENT_CFG = {
  code_agent:     { icon: "👾", color: "#a855f7", bg: "#1e0a2e", zone: "code",     label: "Code Agent" },
  research_agent: { icon: "🔭", color: "#3b82f6", bg: "#0a0e2e", zone: "research", label: "Research Agent" },
  learn_agent:    { icon: "📖", color: "#eab308", bg: "#1a1500", zone: "learn",    label: "Learn Agent" },
  file_agent:     { icon: "🗂",  color: "#22c55e", bg: "#001a0e", zone: "files",    label: "File Agent" },
  general_agent:  { icon: "🤖", color: "#94a3b8", bg: "#0f1117", zone: "general",  label: "General Agent" },
};

const ZONES = [
  { id: "dispatch", label: "DISPATCH",   icon: "🏰", color: "#dc2626", bg: "#1a0000", col: "1 / 4", row: 1 },
  { id: "code",     label: "CODE LAB",   icon: "💻", color: "#a855f7", bg: "#1e0a2e", col: 1,       row: 2 },
  { id: "research", label: "RESEARCH",   icon: "🔭", color: "#3b82f6", bg: "#0a0e2e", col: 2,       row: 2 },
  { id: "learn",    label: "LIBRARY",    icon: "📖", color: "#eab308", bg: "#1a1500", col: 3,       row: 2 },
  { id: "files",    label: "ARCHIVE",    icon: "🗂",  color: "#22c55e", bg: "#001a0e", col: 1,       row: 3 },
  { id: "general",  label: "GENERAL HQ", icon: "🤖", color: "#94a3b8", bg: "#0f1117", col: "2 / 4", row: 3 },
];

const MODEL_COLORS = {
  "claude":         "#c084fc",
  "claude-haiku":   "#a855f7",
  "gemini":         "#60a5fa",
  "ollama/llama3":  "#4ade80",
  "ollama/mistral": "#4ade80",
  "ollama/phi3":    "#4ade80",
};

// ─── CSS animations (injected once) ──────────────────────────────────────────

const GAME_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

  .pf { font-family: 'Press Start 2P', monospace; }

  @keyframes agentWalk {
    0%   { transform: translateY(0px) scale(1); }
    25%  { transform: translateY(-5px) scale(1.05); }
    50%  { transform: translateY(0px) scale(1); }
    75%  { transform: translateY(-3px) scale(1.02); }
  }
  @keyframes agentThink {
    0%,100% { filter: brightness(1); transform: scale(1); }
    50%     { filter: brightness(1.6); transform: scale(1.15); }
  }
  @keyframes agentDone {
    0%   { transform: scale(1) rotate(0deg); }
    20%  { transform: scale(1.4) rotate(-15deg); }
    40%  { transform: scale(1.4) rotate(15deg); }
    60%  { transform: scale(1.2) rotate(-8deg); }
    80%  { transform: scale(1.2) rotate(8deg); }
    100% { transform: scale(1) rotate(0deg); }
  }
  @keyframes agentSpawn {
    0%   { transform: scale(0) rotate(360deg); opacity: 0; }
    70%  { transform: scale(1.3) rotate(-10deg); opacity: 1; }
    100% { transform: scale(1) rotate(0deg); opacity: 1; }
  }
  @keyframes agentFade {
    0%   { transform: scale(1); opacity: 1; }
    100% { transform: scale(0) translateY(-20px); opacity: 0; }
  }
  @keyframes bubblePop {
    0%   { transform: scale(0.5) translateY(4px); opacity: 0; }
    60%  { transform: scale(1.05) translateY(0); opacity: 1; }
    100% { transform: scale(1) translateY(0); opacity: 1; }
  }
  @keyframes scanline {
    0%   { background-position: 0 0; }
    100% { background-position: 0 4px; }
  }
  @keyframes zoneGlow {
    0%,100% { box-shadow: inset 0 0 20px rgba(0,0,0,0.6); }
    50%     { box-shadow: inset 0 0 30px rgba(0,0,0,0.3); }
  }
  @keyframes eventSlide {
    from { transform: translateX(20px); opacity: 0; }
    to   { transform: translateX(0); opacity: 1; }
  }
  @keyframes counterPop {
    0%   { transform: scale(1); }
    50%  { transform: scale(1.4); }
    100% { transform: scale(1); }
  }
  @keyframes routingPulse {
    0%,100% { opacity: 0.6; }
    50%     { opacity: 1; }
  }
  @keyframes dotBounce {
    0%,80%,100% { transform: scale(0.6); opacity: 0.4; }
    40%         { transform: scale(1); opacity: 1; }
  }

  .walk  { animation: agentWalk  0.5s ease-in-out infinite; }
  .think { animation: agentThink 0.8s ease-in-out infinite; }
  .done  { animation: agentDone  0.6s ease-in-out; }
  .spawn { animation: agentSpawn 0.4s cubic-bezier(.36,.07,.19,.97) forwards; }
  .fade  { animation: agentFade  0.5s ease-in forwards; }
  .bubble-pop { animation: bubblePop 0.3s cubic-bezier(.36,.07,.19,.97) forwards; }
  .event-slide { animation: eventSlide 0.25s ease-out; }
  .counter-pop { animation: counterPop 0.3s ease-out; }
  .routing-pulse { animation: routingPulse 1s ease-in-out infinite; }

  .zone-cell {
    position: relative;
    overflow: hidden;
    transition: border-color 0.3s ease;
  }
  .zone-cell::after {
    content: '';
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 3px,
      rgba(0,0,0,0.08) 3px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
  }
  .zone-active {
    animation: zoneGlow 2s ease-in-out infinite;
  }
  .crt-overlay {
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.03) 2px,
      rgba(0,0,0,0.03) 4px
    );
    pointer-events: none;
    z-index: 10;
  }
`;

// ─── Components ───────────────────────────────────────────────────────────────

function SpeechBubble({ text, color }) {
  return (
    <div className="bubble-pop" style={{
      position: "absolute",
      bottom: "calc(100% + 6px)",
      left: "50%",
      transform: "translateX(-50%)",
      background: "#0d0d1a",
      border: `1px solid ${color}`,
      borderRadius: 4,
      padding: "4px 8px",
      fontSize: 7,
      fontFamily: "'Press Start 2P', monospace",
      color: color,
      whiteSpace: "nowrap",
      maxWidth: 180,
      overflow: "hidden",
      textOverflow: "ellipsis",
      zIndex: 20,
      pointerEvents: "none",
      boxShadow: `0 0 8px ${color}44`,
    }}>
      {text.length > 24 ? text.slice(0, 24) + "…" : text}
      <div style={{
        position: "absolute",
        bottom: -5, left: "50%",
        transform: "translateX(-50%)",
        width: 0, height: 0,
        borderLeft: "4px solid transparent",
        borderRight: "4px solid transparent",
        borderTop: `5px solid ${color}`,
      }} />
    </div>
  );
}

function AgentSprite({ agent }) {
  const cfg = AGENT_CFG[agent.type] || AGENT_CFG.general_agent;
  const animClass =
    agent.status === "thinking" || agent.status === "using_tool" ? "think" :
    agent.status === "done"     ? "done"  :
    agent.status === "fading"   ? "fade"  : "walk";

  return (
    <div style={{ position: "relative", display: "inline-flex", flexDirection: "column", alignItems: "center", margin: "4px 6px" }}>
      {(agent.task && agent.status !== "done" && agent.status !== "fading") && (
        <SpeechBubble text={agent.task} color={cfg.color} />
      )}
      <div className={`${animClass} spawn`} style={{ fontSize: 28, cursor: "default", userSelect: "none" }}>
        {cfg.icon}
      </div>
      <div style={{
        fontFamily: "'Press Start 2P', monospace",
        fontSize: 5,
        color: cfg.color,
        marginTop: 2,
        textAlign: "center",
        maxWidth: 60,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}>
        {agent.status === "thinking"   ? "THINKING" :
         agent.status === "using_tool" ? `TOOL: ${agent.tool || "..."}` :
         agent.status === "done"       ? "DONE!" :
         agent.status === "routing"    ? "ROUTING..." : "IDLE"}
      </div>
      {(agent.status === "thinking" || agent.status === "using_tool") && (
        <div style={{ display: "flex", gap: 2, marginTop: 3 }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={{
              width: 4, height: 4,
              borderRadius: "50%",
              background: cfg.color,
              animation: `dotBounce 1.2s ease-in-out ${i * 0.15}s infinite`,
            }} />
          ))}
        </div>
      )}
    </div>
  );
}

function ZoneCell({ zone, agents }) {
  const zoneAgents = agents.filter(a => {
    const cfg = AGENT_CFG[a.type] || AGENT_CFG.general_agent;
    return cfg.zone === zone.id || (zone.id === "dispatch" && a.status === "routing");
  });
  const isActive = zoneAgents.length > 0;

  return (
    <div className={`zone-cell ${isActive ? "zone-active" : ""}`} style={{
      gridColumn: zone.col,
      gridRow: zone.row,
      background: zone.bg,
      border: `2px solid ${isActive ? zone.color : zone.color + "44"}`,
      borderRadius: 4,
      padding: 10,
      minHeight: zone.row === 1 ? 90 : 130,
      display: "flex",
      flexDirection: "column",
      transition: "border-color 0.4s ease",
    }}>
      {/* Zone header */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 14 }}>{zone.icon}</span>
        <span style={{
          fontFamily: "'Press Start 2P', monospace",
          fontSize: 7,
          color: isActive ? zone.color : zone.color + "88",
          letterSpacing: 1,
          transition: "color 0.3s",
        }}>
          {zone.label}
        </span>
        {isActive && (
          <span style={{
            marginLeft: "auto",
            fontFamily: "'Press Start 2P', monospace",
            fontSize: 7,
            color: zone.color,
            background: zone.color + "22",
            padding: "2px 5px",
            borderRadius: 2,
          }}>
            {zoneAgents.length} ACTIVE
          </span>
        )}
      </div>

      {/* Agents */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", flex: 1 }}>
        {zoneAgents.map(a => <AgentSprite key={a.id} agent={a} />)}
        {!isActive && (
          <div style={{
            fontFamily: "'Press Start 2P', monospace",
            fontSize: 6,
            color: zone.color + "33",
            alignSelf: "center",
            margin: "auto",
          }}>
            EMPTY
          </div>
        )}
      </div>
    </div>
  );
}

function StatsBar({ stats, costs }) {
  const StatBox = ({ label, value, color, flash }) => (
    <div style={{
      background: "#0d0d1a",
      border: `1px solid ${color}44`,
      borderRadius: 4,
      padding: "8px 14px",
      textAlign: "center",
    }}>
      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 16, color, marginBottom: 4 }}
           className={flash ? "counter-pop" : ""}>{value}</div>
      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 6, color: color + "88" }}>{label}</div>
    </div>
  );

  return (
    <div style={{ display: "flex", gap: 8, padding: "8px 12px", background: "#050509", borderBottom: "1px solid #1a1a2e", flexWrap: "wrap" }}>
      <StatBox label="ACTIVE"    value={stats.active}    color="#f97316" />
      <StatBox label="COMPLETED" value={stats.completed} color="#22c55e" flash={stats.completedFlash} />
      <StatBox label="TOTAL"     value={stats.total}     color="#60a5fa" />
      <StatBox label="ROUTING"   value={stats.routing}   color="#dc2626" />
      {costs?.total_cost_usd !== undefined && (
        <StatBox label="COST $USD" value={`$${costs.total_cost_usd.toFixed(4)}`} color="#a855f7" />
      )}
      {costs?.cache_read_tokens > 0 && (
        <StatBox label="CACHED" value={`${(costs.cache_read_tokens / 1000).toFixed(1)}K`} color="#eab308" />
      )}
    </div>
  );
}

function EventLog({ events }) {
  const TYPE_COLOR = {
    routing:       "#dc2626",
    agent_start:   "#3b82f6",
    agent_thinking:"#a855f7",
    agent_tools:   "#eab308",
    agent_done:    "#22c55e",
  };
  const TYPE_LABEL = {
    routing:        "ROUTING",
    agent_start:    "SPAWN",
    agent_thinking: "THINK",
    agent_tools:    "TOOLS",
    agent_done:     "DONE",
  };

  return (
    <div style={{ height: 140, overflowY: "auto", background: "#050509", borderTop: "1px solid #1a1a2e", padding: "6px 10px" }}>
      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 6, color: "#334155", marginBottom: 6 }}>
        EVENT LOG
      </div>
      {[...events].reverse().slice(0, 30).map((ev) => {
        const color = TYPE_COLOR[ev.type] || "#475569";
        return (
          <div key={ev.id} className="event-slide" style={{ display: "flex", gap: 8, marginBottom: 3, alignItems: "center" }}>
            <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 5, color: "#334155", minWidth: 50 }}>
              {ev.time}
            </span>
            <span style={{
              fontFamily: "'Press Start 2P', monospace", fontSize: 5,
              color, background: color + "22", padding: "1px 4px", borderRadius: 2, minWidth: 52,
            }}>
              {TYPE_LABEL[ev.type] || ev.type.toUpperCase()}
            </span>
            <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 5, color: "#64748b" }}>
              [{ev.agent_id || "—"}]
            </span>
            {ev.detail && (
              <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 5, color: "#475569", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {ev.detail}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── World View ───────────────────────────────────────────────────────────────

function WorldView({ agents, stats, costs, events, wsStatus }) {
  const agentList = Object.values(agents);

  const statusColor = wsStatus === "connected" ? "#22c55e" : wsStatus === "connecting" ? "#eab308" : "#dc2626";
  const statusLabel = wsStatus === "connected" ? "LIVE"      : wsStatus === "connecting" ? "CONNECTING" : "OFFLINE";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "#050509", position: "relative" }}>
      <div className="crt-overlay" />
      <style>{GAME_CSS}</style>

      {/* Title bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "6px 12px", background: "#0a0a1a", borderBottom: "1px solid #1a1a2e",
      }}>
        <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 10, color: "#7c3aed" }}>
          AGENT WORLD
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor, boxShadow: `0 0 6px ${statusColor}` }} />
          <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: 6, color: statusColor }}>
            {statusLabel}
          </span>
        </div>
      </div>

      {/* Stats */}
      <StatsBar stats={stats} costs={costs} />

      {/* Game grid */}
      <div style={{ flex: 1, overflow: "auto", padding: 10 }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gridTemplateRows: "auto auto auto",
          gap: 8,
          minHeight: "100%",
        }}>
          {ZONES.map(zone => (
            <ZoneCell key={zone.id} zone={zone} agents={agentList} />
          ))}
        </div>
      </div>

      {/* Event log */}
      <EventLog events={events} />
    </div>
  );
}

// ─── Chat View ────────────────────────────────────────────────────────────────

function ChatView({ sessionId, messages, setMessages }) {
  const [input, setInput]   = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const text = input;
    setMessages(prev => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId, show_routing: false }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.response,
        model: data.model_used,
        agent: data.agent_used,
        tools: data.tools_used,
        reasoning: data.reasoning,
      }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: "error", content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const agentCfg = (name) => AGENT_CFG[name] || { icon: "🤖", color: "#94a3b8" };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "#475569", marginTop: 60 }}>
            <div style={{ fontSize: 48 }}>🧠</div>
            <p style={{ marginTop: 12, color: "#64748b" }}>How can I help you?</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{ maxWidth: "75%" }}>
              {msg.role === "assistant" && msg.model && (
                <div style={{ display: "flex", gap: 8, marginBottom: 4, fontSize: 11, color: "#475569", alignItems: "center" }}>
                  <span style={{ color: MODEL_COLORS[msg.model] || "#94a3b8" }}>◆ {msg.model}</span>
                  <span>{agentCfg(msg.agent).icon} {msg.agent}</span>
                  {msg.tools?.length > 0 && <span style={{ color: "#ca8a04" }}>🔧 {msg.tools.join(", ")}</span>}
                </div>
              )}
              <div style={{
                borderRadius: 14,
                padding: "10px 14px",
                fontSize: 13,
                lineHeight: 1.6,
                background:
                  msg.role === "user"  ? "#1d4ed8" :
                  msg.role === "error" ? "#450a0a"  : "#1e1e2e",
                color:
                  msg.role === "error" ? "#fca5a5" : "#e2e8f0",
                borderBottomRightRadius: msg.role === "user" ? 4 : 14,
                borderBottomLeftRadius:  msg.role === "user" ? 14 : 4,
              }}>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{msg.content}</pre>
              </div>
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ display: "flex" }}>
            <div style={{ background: "#1e1e2e", borderRadius: 14, borderBottomLeftRadius: 4, padding: "10px 14px" }}>
              <div style={{ display: "flex", gap: 4 }}>
                {[0,1,2].map(i => (
                  <div key={i} style={{ width: 7, height: 7, borderRadius: "50%", background: "#475569",
                    animation: `dotBounce 1.2s ease-in-out ${i*0.15}s infinite` }} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: "12px 16px", background: "#0a0a1a", borderTop: "1px solid #1e1e2e" }}>
        <div style={{ display: "flex", gap: 8, maxWidth: 800, margin: "0 auto" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder="Ask a question… (Enter to send)"
            rows={1}
            style={{
              flex: 1, background: "#1e1e2e", color: "#e2e8f0",
              border: "1px solid #334155", borderRadius: 12,
              padding: "10px 14px", fontSize: 13, resize: "none",
              outline: "none", fontFamily: "inherit",
            }}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            style={{
              background: loading || !input.trim() ? "#1e293b" : "#2563eb",
              color: "#e2e8f0", border: "none", borderRadius: 12,
              padding: "10px 18px", cursor: loading ? "not-allowed" : "pointer",
              fontSize: 16, transition: "background 0.2s",
            }}
          >↑</button>
        </div>
      </div>
    </div>
  );
}

// ─── Root App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [view,      setView]      = useState("world");
  const [agents,    setAgents]    = useState({});
  const [events,    setEvents]    = useState([]);
  const [wsStatus,  setWsStatus]  = useState("connecting");
  const [costs,     setCosts]     = useState(null);
  const [stats,     setStats]     = useState({ active: 0, completed: 0, total: 0, routing: 0, completedFlash: false });
  const [messages,   setMessages]  = useState([]);
  const [sessionId,  setSessionId] = useState(null);  // null during SSR, set after mount

  // Initialize session_id from localStorage — client-side only
  useEffect(() => {
    let sid = localStorage.getItem("agent_session_id");
    if (!sid) {
      sid = "session-" + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("agent_session_id", sid);
    }
    setSessionId(sid);
  }, []);
  const eventIdRef  = useRef(0);

  const addEvent = useCallback((ev) => {
    const now = new Date();
    const time = now.toTimeString().slice(0, 8);
    setEvents(prev => [...prev.slice(-99), { ...ev, id: eventIdRef.current++, time }]);
  }, []);

  // Load history from MongoDB when session_id is ready
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_URL}/history/${sessionId}`)
      .then(r => r.json())
      .then(data => {
        if (data.messages?.length > 0) {
          setMessages(data.messages.map(m => ({
            role:    m.role,
            content: m.content,
            model:   m.model,
            agent:   m.agent,
            tools:   m.tools,
          })));
        }
      })
      .catch(() => {});
  }, [sessionId]);

  // WebSocket
  useEffect(() => {
    let ws;
    let retryTimer;

    const connect = () => {
      setWsStatus("connecting");
      ws = new WebSocket(WS_URL);

      ws.onopen  = () => setWsStatus("connected");
      ws.onclose = () => {
        setWsStatus("offline");
        retryTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        if (ev.type === "ping") return;

        addEvent({
          type:     ev.type,
          agent_id: ev.agent_id,
          detail:   ev.task || ev.tool || (ev.tools?.join(", ")) || (ev.duration_ms ? `${ev.duration_ms}ms` : ""),
        });

        switch (ev.type) {

          case "routing":
            setStats(s => ({ ...s, routing: s.routing + 1, total: s.total + 1 }));
            setAgents(prev => ({
              ...prev,
              [ev.agent_id]: { id: ev.agent_id, type: "general_agent", status: "routing", task: ev.task },
            }));
            break;

          case "agent_start":
            setStats(s => ({ ...s, active: s.active + 1 }));
            setAgents(prev => ({
              ...prev,
              [ev.agent_id]: {
                id:       ev.agent_id,
                type:     ev.agent_type,
                model:    ev.model,
                task:     ev.task,
                status:   "idle",
                tools:    ev.tools,
              },
            }));
            break;

          case "agent_thinking":
            setAgents(prev => prev[ev.agent_id]
              ? { ...prev, [ev.agent_id]: { ...prev[ev.agent_id], status: "thinking" } }
              : prev
            );
            break;

          case "agent_tools":
            setAgents(prev => prev[ev.agent_id]
              ? { ...prev, [ev.agent_id]: { ...prev[ev.agent_id], status: "using_tool", tool: ev.tools?.[0] } }
              : prev
            );
            break;

          case "agent_done":
            setStats(s => ({ ...s, active: Math.max(0, s.active - 1), completed: s.completed + 1, completedFlash: true }));
            setTimeout(() => setStats(s => ({ ...s, completedFlash: false })), 400);
            setAgents(prev => prev[ev.agent_id]
              ? { ...prev, [ev.agent_id]: { ...prev[ev.agent_id], status: "done" } }
              : prev
            );
            setTimeout(() => {
              setAgents(prev => {
                const next = { ...prev };
                if (next[ev.agent_id]) next[ev.agent_id] = { ...next[ev.agent_id], status: "fading" };
                return next;
              });
              setTimeout(() => setAgents(prev => { const n = { ...prev }; delete n[ev.agent_id]; return n; }), 600);
            }, 2000);
            // Fetch updated costs
            fetch(`${API_URL}/stats?session_id=${sessionId}`)
              .then(r => r.json())
              .then(d => { if (d.costs) setCosts(d.costs); })
              .catch(() => {});
            break;
        }
      };
    };

    connect();
    return () => { clearTimeout(retryTimer); ws?.close(); };
  }, [addEvent]);

  const TAB = ({ id, label, icon }) => (
    <button
      onClick={() => setView(id)}
      style={{
        background: view === id ? "#1e1e2e" : "transparent",
        color:      view === id ? "#e2e8f0" : "#475569",
        border:     "none",
        borderBottom: view === id ? "2px solid #7c3aed" : "2px solid transparent",
        padding: "10px 18px",
        cursor: "pointer",
        fontSize: 13,
        fontWeight: 600,
        transition: "all 0.2s",
        display: "flex", alignItems: "center", gap: 6,
      }}
    >
      {icon} {label}
    </button>
  );

  const activeCount = Object.values(agents).filter(a => a.status !== "fading").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#0a0a1a", color: "#e2e8f0" }}>
      <style>{GAME_CSS}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 16px", background: "#050509", borderBottom: "1px solid #1a1a2e", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 20 }}>🤖</span>
          <span style={{ fontWeight: 700, fontSize: 15 }}>Agent System</span>
          <span style={{ fontSize: 12, color: "#475569" }}>Claude · Gemini · Ollama</span>
        </div>
        <div style={{ display: "flex" }}>
          <TAB id="world" icon="🎮" label="World" />
          <TAB id="chat"  icon="💬" label="Chat" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {activeCount > 0 && (
            <div style={{
              fontFamily: "'Press Start 2P', monospace", fontSize: 8,
              color: "#f97316", background: "#1a0a00", padding: "4px 8px", borderRadius: 4,
              border: "1px solid #f9731644",
            }}>
              {activeCount} AGENT{activeCount !== 1 ? "S" : ""} ACTIVE
            </div>
          )}
          <div style={{ width: 8, height: 8, borderRadius: "50%",
            background: wsStatus === "connected" ? "#22c55e" : "#dc2626",
            boxShadow: `0 0 8px ${wsStatus === "connected" ? "#22c55e" : "#dc2626"}` }} />
        </div>
      </div>

      {/* Content — both views always mounted, CSS hides the inactive one */}
      <div style={{ flex: 1, display: view === "world" ? "flex" : "none", flexDirection: "column", overflow: "hidden" }}>
        <WorldView agents={agents} stats={stats} costs={costs} events={events} wsStatus={wsStatus} />
      </div>
      <div style={{ flex: 1, display: view === "chat" ? "flex" : "none", flexDirection: "column", overflow: "hidden" }}>
        <ChatView sessionId={sessionId} messages={messages} setMessages={setMessages} />
      </div>
    </div>
  );
}

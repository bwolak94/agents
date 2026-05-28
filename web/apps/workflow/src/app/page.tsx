"use client";

export const dynamic = "force-dynamic";

import { useState, useCallback, useRef } from "react";
import type { CSSProperties } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Types ─────────────────────────────────────────────────────────────────────
interface NodeDef {
  id: string;
  name: string;
  type: "llm" | "human" | "transform";
  model?: string;
  prompt_key?: string;
  output_key?: string;
  x: number;
  y: number;
}

interface EdgeDef {
  id: string;
  src: string;
  dst: string;
  condition_key?: string;
}

interface WorkflowDef {
  workflow_id: string;
  name: string;
  nodes: NodeDef[];
  edges: EdgeDef[];
}

// ─── Run history ───────────────────────────────────────────────────────────────
interface RunInfo { run_id: string; status: string; workflow_id: string; }

const NODE_W = 160;
const NODE_H = 64;

export default function WorkflowBuilderPage() {
  const [nodes, setNodes] = useState<NodeDef[]>([
    { id: "start", name: "START",   type: "transform", x: 40,  y: 180 },
    { id: "step1", name: "Step 1",  type: "llm",       x: 260, y: 180, model: "claude", prompt_key: "message", output_key: "step1_result" },
    { id: "end",   name: "END",     type: "transform", x: 480, y: 180 },
  ]);
  const [edges, setEdges] = useState<EdgeDef[]>([
    { id: "e1", src: "start", dst: "step1" },
    { id: "e2", src: "step1", dst: "end" },
  ]);
  const [workflowId, setWorkflowId] = useState("my-workflow");
  const [workflowName, setWorkflowName] = useState("My Workflow");
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [status, setStatus] = useState<string>("");
  const [dragging, setDragging] = useState<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const [selectedNode, setSelectedNode] = useState<NodeDef | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // ─── Drag ──────────────────────────────────────────────────────────────────
  const onMouseDown = (e: React.MouseEvent, node: NodeDef) => {
    if (node.id === "start" || node.id === "end") return;
    const rect = (e.target as Element).closest("svg")?.getBoundingClientRect();
    if (!rect) return;
    setDragging({ id: node.id, offsetX: e.clientX - rect.left - node.x, offsetY: e.clientY - rect.top - node.y });
  };

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const nx = e.clientX - rect.left - dragging.offsetX;
    const ny = e.clientY - rect.top  - dragging.offsetY;
    setNodes(prev => prev.map(n => n.id === dragging.id ? { ...n, x: Math.max(0, nx), y: Math.max(0, ny) } : n));
  }, [dragging]);

  const onMouseUp = () => setDragging(null);

  // ─── Add node ──────────────────────────────────────────────────────────────
  const addNode = () => {
    const id = `node_${Date.now()}`;
    setNodes(prev => [...prev, { id, name: "New Node", type: "llm", x: 200, y: 300, model: "claude", prompt_key: "message", output_key: `${id}_result` }]);
  };

  // ─── Delete node ───────────────────────────────────────────────────────────
  const deleteNode = (id: string) => {
    if (id === "start" || id === "end") return;
    setNodes(prev => prev.filter(n => n.id !== id));
    setEdges(prev => prev.filter(e => e.src !== id && e.dst !== id));
    if (selectedNode?.id === id) setSelectedNode(null);
  };

  // ─── Save workflow ─────────────────────────────────────────────────────────
  const saveWorkflow = async () => {
    const definition = {
      nodes: nodes.map(({ id, name, type, model, prompt_key, output_key }) => ({ name: id, label: name, type, model, prompt_key, output_key })),
      edges: edges.map(({ src, dst, condition_key }) => ({ src, dst, condition_key })),
    };
    try {
      const res = await fetch(`${API}/workflows`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_id: workflowId, name: workflowName, definition }),
      });
      const data = await res.json();
      setStatus(res.ok ? `Saved: ${data.workflow_id}` : `Error: ${JSON.stringify(data)}`);
    } catch (e) {
      setStatus(`Network error: ${e}`);
    }
  };

  // ─── Run workflow ──────────────────────────────────────────────────────────
  const runWorkflow = async () => {
    try {
      const res = await fetch(`${API}/workflows/${workflowId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_data: { message: "Hello from workflow builder" }, session_id: "workflow-builder", persist: true }),
      });
      const data = await res.json();
      if (res.ok) {
        setRuns(prev => [{ run_id: data.run_id, status: "started", workflow_id: workflowId }, ...prev.slice(0, 9)]);
        setStatus(`Started run: ${data.run_id}`);
      } else {
        setStatus(`Run error: ${JSON.stringify(data)}`);
      }
    } catch (e) {
      setStatus(`Network error: ${e}`);
    }
  };

  // ─── Edge drawing helper ───────────────────────────────────────────────────
  const getNodeCenter = (id: string) => {
    const n = nodes.find(x => x.id === id);
    if (!n) return { x: 0, y: 0 };
    return { x: n.x + NODE_W / 2, y: n.y + NODE_H / 2 };
  };

  const nodeColor = (type: string) => ({
    llm:       "#312e81",
    human:     "#713f12",
    transform: "#1e3a5f",
  }[type] || "#1e293b");

  const nodeBorder = (type: string) => ({
    llm:       "#6366f1",
    human:     "#f59e0b",
    transform: "#3b82f6",
  }[type] || "#334155");

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", background: "#0f172a", minHeight: "100vh", color: "#f1f5f9", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <header style={{ padding: "1rem 1.5rem", borderBottom: "1px solid #334155", display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, flex: "0 0 auto" }}>Workflow Builder</h1>
        <input value={workflowId} onChange={e => setWorkflowId(e.target.value)} placeholder="workflow-id"
          style={{ padding: "0.375rem 0.625rem", background: "#1e293b", border: "1px solid #334155", borderRadius: "0.375rem", color: "#f1f5f9", fontSize: "0.875rem", width: 140 }} />
        <input value={workflowName} onChange={e => setWorkflowName(e.target.value)} placeholder="Workflow name"
          style={{ padding: "0.375rem 0.625rem", background: "#1e293b", border: "1px solid #334155", borderRadius: "0.375rem", color: "#f1f5f9", fontSize: "0.875rem", width: 200 }} />
        <button onClick={addNode} style={btnStyle("#334155", "#94a3b8")}>+ Add Node</button>
        <button onClick={saveWorkflow} style={btnStyle("#312e81", "#a5b4fc")}>Save</button>
        <button onClick={runWorkflow} style={btnStyle("#14532d", "#86efac")}>▶ Run</button>
        {status && <span style={{ fontSize: "0.8125rem", color: "#94a3b8", marginLeft: "auto" }}>{status}</span>}
      </header>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Canvas */}
        <svg ref={svgRef} style={{ flex: 1, cursor: dragging ? "grabbing" : "default" }}
             onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
          <defs>
            <marker id="arrow" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
              <polygon points="0 0, 10 3.5, 0 7" fill="#475569" />
            </marker>
          </defs>

          {/* Edges */}
          {edges.map(edge => {
            const from = getNodeCenter(edge.src);
            const to   = getNodeCenter(edge.dst);
            const dx = to.x - from.x;
            const cx = from.x + dx * 0.5;
            return (
              <g key={edge.id}>
                <path d={`M ${from.x} ${from.y} C ${cx} ${from.y}, ${cx} ${to.y}, ${to.x} ${to.y}`}
                      stroke="#475569" strokeWidth={2} fill="none" markerEnd="url(#arrow)" />
                {edge.condition_key && (
                  <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 6}
                        fill="#f59e0b" fontSize="10" textAnchor="middle">{edge.condition_key}</text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map(node => (
            <g key={node.id} transform={`translate(${node.x}, ${node.y})`}
               onMouseDown={e => onMouseDown(e, node)}
               onClick={() => setSelectedNode(node)}
               style={{ cursor: node.id === "start" || node.id === "end" ? "default" : "grab" }}>
              <rect width={NODE_W} height={NODE_H} rx={8}
                    fill={nodeColor(node.type)}
                    stroke={selectedNode?.id === node.id ? "#f1f5f9" : nodeBorder(node.type)}
                    strokeWidth={selectedNode?.id === node.id ? 2 : 1} />
              <text x={NODE_W / 2} y={24} textAnchor="middle" fill="#e2e8f0" fontSize={13} fontWeight={600}>{node.name}</text>
              <text x={NODE_W / 2} y={42} textAnchor="middle" fill="#94a3b8" fontSize={10}>{node.type}{node.model ? ` · ${node.model}` : ""}</text>
              {node.id !== "start" && node.id !== "end" && (
                <text x={NODE_W - 10} y={16} textAnchor="middle" fill="#ef4444" fontSize={14} fontWeight={700}
                      style={{ cursor: "pointer" }} onClick={e => { e.stopPropagation(); deleteNode(node.id); }}>×</text>
              )}
            </g>
          ))}
        </svg>

        {/* Properties panel */}
        {selectedNode && (
          <aside style={{ width: 240, background: "#1e293b", borderLeft: "1px solid #334155", padding: "1rem", fontSize: "0.875rem", overflowY: "auto" }}>
            <h3 style={{ margin: "0 0 0.75rem", color: "#94a3b8", textTransform: "uppercase", fontSize: "0.75rem", letterSpacing: "0.05em" }}>Node Properties</h3>
            {[
              { label: "Name",       key: "name" },
              { label: "Type",       key: "type" },
              { label: "Model",      key: "model" },
              { label: "Prompt Key", key: "prompt_key" },
              { label: "Output Key", key: "output_key" },
            ].map(({ label, key }) => (
              <div key={key} style={{ marginBottom: "0.625rem" }}>
                <label style={{ display: "block", color: "#94a3b8", marginBottom: "0.25rem", fontSize: "0.75rem" }}>{label}</label>
                <input value={(selectedNode as any)[key] || ""} onChange={e => {
                  const val = e.target.value;
                  setNodes(prev => prev.map(n => n.id === selectedNode.id ? { ...n, [key]: val } : n));
                  setSelectedNode(prev => prev ? { ...prev, [key]: val } : null);
                }} style={{ width: "100%", padding: "0.375rem 0.5rem", background: "#0f172a", border: "1px solid #334155", borderRadius: "0.375rem", color: "#f1f5f9", fontSize: "0.8125rem", boxSizing: "border-box" }} />
              </div>
            ))}
          </aside>
        )}
      </div>

      {/* Run log */}
      {runs.length > 0 && (
        <footer style={{ background: "#1e293b", borderTop: "1px solid #334155", padding: "0.75rem 1.5rem" }}>
          <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: "0.375rem" }}>Recent Runs</div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {runs.map(r => (
              <span key={r.run_id} style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: "0.375rem", padding: "0.25rem 0.5rem", fontSize: "0.75rem", fontFamily: "monospace" }}>
                {r.run_id.slice(0, 8)} — <span style={{ color: "#22c55e" }}>{r.status}</span>
              </span>
            ))}
          </div>
        </footer>
      )}
    </div>
  );
}

function btnStyle(bg: string, color: string): CSSProperties {
  return { padding: "0.375rem 0.875rem", background: bg, color, border: "none", borderRadius: "0.375rem", cursor: "pointer", fontSize: "0.875rem", fontWeight: 500 };
}

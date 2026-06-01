'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_URL } from '@/constants/api';

interface GraphNode {
  id: string;
  group: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  label: string;
  confidence: number;
}

interface Props {
  sessionId: string;
}

// Simple force simulation (no external lib needed)
function useForce(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});

  useEffect(() => {
    if (!nodes.length) return;

    const pos: Record<string, { x: number; y: number; vx: number; vy: number }> = {};
    nodes.forEach((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2;
      const r = Math.min(width, height) * 0.3;
      pos[n.id] = {
        x: width / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 40,
        y: height / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 40,
        vx: 0, vy: 0,
      };
    });

    let frame = 0;
    const simulate = () => {
      const k = 0.3;
      const repulse = 1200;
      const attract = 0.05;
      const damping = 0.85;

      // Repulsion between all node pairs
      const ids = Object.keys(pos);
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = pos[ids[i]];
          const b = pos[ids[j]];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const f = repulse / (dist * dist);
          a.vx -= f * dx / dist;
          a.vy -= f * dy / dist;
          b.vx += f * dx / dist;
          b.vy += f * dy / dist;
        }
      }

      // Attraction along edges
      edges.forEach(e => {
        const s = pos[e.source];
        const t = pos[e.target];
        if (!s || !t) return;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const desired = 100;
        const f = attract * (dist - desired);
        s.vx += f * dx / dist;
        s.vy += f * dy / dist;
        t.vx -= f * dx / dist;
        t.vy -= f * dy / dist;
      });

      // Center gravity
      Object.values(pos).forEach(p => {
        p.vx += (width / 2 - p.x) * k * 0.01;
        p.vy += (height / 2 - p.y) * k * 0.01;
        p.vx *= damping;
        p.vy *= damping;
        p.x = Math.max(30, Math.min(width - 30, p.x + p.vx));
        p.y = Math.max(30, Math.min(height - 30, p.y + p.vy));
      });

      setPositions(Object.fromEntries(Object.entries(pos).map(([k, v]) => [k, { x: v.x, y: v.y }])));
      frame++;
      if (frame < 120) requestAnimationFrame(simulate);
    };
    requestAnimationFrame(simulate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes.length, edges.length, width, height]);

  return positions;
}

export function KnowledgeGraph({ sessionId }: Props) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 800, h: 500 });

  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      const e = entries[0];
      if (e) setSize({ w: e.contentRect.width, h: e.contentRect.height });
    });
    if (svgRef.current) obs.observe(svgRef.current);
    return () => obs.disconnect();
  }, []);

  const load = useCallback(() => {
    if (!sessionId) return;
    setLoading(true);
    fetch(`${API_URL}/memory/graph?session_id=${encodeURIComponent(sessionId)}&limit=200`)
      .then(r => r.json())
      .then(d => {
        setNodes(d.nodes ?? []);
        setEdges(d.edges ?? []);
        setTotal(d.total_facts ?? 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  const positions = useForce(nodes, edges, size.w, size.h);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-faint text-sm">
        Loading knowledge graph…
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-text-faint">
        <div className="text-4xl">🕸</div>
        <p className="text-sm">No memory facts yet for this session.</p>
        <p className="text-xs text-border-strong">Facts are extracted automatically during conversations.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-2 border-b border-border-dim flex items-center justify-between flex-shrink-0">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-widest">Knowledge Graph</span>
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-text-faint">{total} facts · {nodes.length} nodes · {edges.length} edges</span>
          <button
            onClick={load}
            title="Refresh graph"
            className="text-[11px] border border-border-strong rounded px-2 py-0.5 text-text-faint hover:text-text-secondary transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        style={{ flex: 1, width: '100%', height: '100%' }}
        className="bg-surface-base"
      >
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#334155" />
          </marker>
        </defs>

        {/* Edges */}
        {edges.map((e, i) => {
          const s = positions[e.source];
          const t = positions[e.target];
          if (!s || !t) return null;
          const mx = (s.x + t.x) / 2;
          const my = (s.y + t.y) / 2;
          return (
            <g key={i}>
              <line
                x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                stroke="#334155"
                strokeWidth={1 + e.confidence}
                markerEnd="url(#arrow)"
                opacity={0.6}
              />
              <text x={mx} y={my - 4} fontSize={9} fill="#64748b" textAnchor="middle">
                {e.label}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {nodes.map(n => {
          const p = positions[n.id];
          if (!p) return null;
          const isEntity = n.group === 'entity';
          const isHov = hovered === n.id;
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: 'default' }}
            >
              <circle
                r={isHov ? 14 : isEntity ? 10 : 8}
                fill={isEntity ? '#1d4ed8' : '#0f766e'}
                stroke={isHov ? '#60a5fa' : '#1e293b'}
                strokeWidth={isHov ? 2 : 1}
                style={{ transition: 'r 0.15s, stroke 0.15s' }}
              />
              <text
                y={-15}
                fontSize={isHov ? 12 : 10}
                fill="#e2e8f0"
                textAnchor="middle"
                style={{ pointerEvents: 'none', userSelect: 'none' }}
              >
                {n.id.length > 20 ? n.id.slice(0, 18) + '…' : n.id}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="px-4 py-2 border-t border-border-dim flex items-center gap-4 flex-shrink-0 text-[10px] text-text-faint">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-blue-700" />
          <span>Entity</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-teal-700" />
          <span>Value</span>
        </div>
        <span className="ml-auto">Hover nodes to highlight</span>
      </div>
    </div>
  );
}

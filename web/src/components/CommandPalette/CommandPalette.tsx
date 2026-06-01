'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_URL } from '@/constants/api';
import type { ViewId } from '@/components/Header/Header';

interface Command {
  id: string;
  label: string;
  description?: string;
  group?: string;
  action: () => void;
}

interface CommandPaletteProps {
  onViewChange: (view: ViewId) => void;
  onNewSession: () => void;
  onSelectSession?: (id: string) => void;
  sessionId: string | null;
}

export function CommandPalette({ onViewChange, onNewSession, onSelectSession, sessionId }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [sessions, setSessions] = useState<{ session_id: string; preview: string }[]>([]);
  const [agents, setAgents] = useState<string[]>([]);
  const [macros, setMacros] = useState<{ name: string; description: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Cmd+K / Ctrl+K opens the palette
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === 'Escape') {
        setOpen(false);
        setQuery('');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
      // Lazy-load sessions, agents, macros when palette opens
      fetch(`${API_URL}/sessions?limit=20`).then(r => r.json()).then(d => {
        setSessions((d.sessions ?? []).map((s: { session_id: string; preview?: string }) => ({
          session_id: s.session_id,
          preview: (s.preview ?? s.session_id).slice(0, 60),
        })));
      }).catch(() => {});
      fetch(`${API_URL}/agents`).then(r => r.json()).then(d => {
        setAgents(Object.keys(d.agents ?? {}));
      }).catch(() => {});
      fetch(`${API_URL}/macros`).then(r => r.json()).then(d => {
        setMacros((d.macros ?? []).map((m: { name: string; description?: string }) => ({
          name: m.name,
          description: m.description ?? '',
        })));
      }).catch(() => {});
    } else {
      setQuery('');
    }
  }, [open]);

  const close = useCallback(() => { setOpen(false); setQuery(''); }, []);

  const staticCommands: Command[] = [
    { id: 'chat',       label: 'Go to Chat',       description: 'Switch to chat view',      group: 'Navigate', action: () => { onViewChange('chat'); close(); } },
    { id: 'analytics',  label: 'Go to Analytics',   description: 'View analytics dashboard', group: 'Navigate', action: () => { onViewChange('analytics'); close(); } },
    { id: 'memory',     label: 'Go to Memory',      description: 'Inspect agent memory',     group: 'Navigate', action: () => { onViewChange('memory'); close(); } },
    { id: 'branch',     label: 'Go to Branch',      description: 'Fork sessions',            group: 'Navigate', action: () => { onViewChange('branch'); close(); } },
    { id: 'plugins',    label: 'Go to Plugins',     description: 'Community plugins',        group: 'Navigate', action: () => { onViewChange('plugins'); close(); } },
    { id: 'ab-test',    label: 'Go to A/B Test',    description: 'System prompt A/B testing',group: 'Navigate', action: () => { onViewChange('ab-test'); close(); } },
    { id: 'new-session',label: 'New Session',        description: 'Start a new conversation', group: 'Actions',  action: () => { onNewSession(); close(); } },
    {
      id: 'export-md',
      label: 'Export as Markdown',
      description: 'Download current chat as .md',
      group: 'Actions',
      action: async () => {
        if (!sessionId) return;
        close();
        const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=md`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `${sessionId}.md`; a.click();
        URL.revokeObjectURL(url);
      },
    },
    {
      id: 'export-json',
      label: 'Export as JSON',
      description: 'Download current chat as .json',
      group: 'Actions',
      action: async () => {
        if (!sessionId) return;
        close();
        const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=json`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `${sessionId}.json`; a.click();
        URL.revokeObjectURL(url);
      },
    },
    {
      id: 'snapshot',
      label: 'Save Snapshot',
      description: 'Freeze current session state with resume prompt',
      group: 'Actions',
      action: async () => {
        if (!sessionId) return;
        close();
        const name = `Snapshot ${new Date().toLocaleString()}`;
        await fetch(`${API_URL}/sessions/${sessionId}/snapshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        }).catch(() => {});
      },
    },
  ];

  // Dynamic commands from loaded data
  const sessionCmds: Command[] = sessions.map(s => ({
    id: `session-${s.session_id}`,
    label: s.preview || s.session_id,
    description: `Open session: ${s.session_id}`,
    group: 'Recent Sessions',
    action: () => { onSelectSession?.(s.session_id); close(); },
  }));

  const agentCmds: Command[] = agents.map(a => ({
    id: `agent-${a}`,
    label: a,
    description: `Select agent: ${a}`,
    group: 'Agents',
    action: () => close(),
  }));

  const macroCmds: Command[] = macros.map(m => ({
    id: `macro-${m.name}`,
    label: m.name,
    description: m.description || `Expand macro ${m.name}`,
    group: 'Macros',
    action: () => close(),
  }));

  const allCommands = [...staticCommands, ...sessionCmds, ...agentCmds, ...macroCmds];

  const filtered = query.trim()
    ? allCommands.filter(
        (c) =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          c.description?.toLowerCase().includes(query.toLowerCase()) ||
          c.group?.toLowerCase().includes(query.toLowerCase()),
      )
    : allCommands;

  const [selected, setSelected] = useState(0);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === 'Enter') {
      filtered[selected]?.action();
    } else if (e.key === 'Escape') {
      close();
    }
  }, [filtered, selected, close]);

  useEffect(() => { setSelected(0); }, [query]);

  if (!open) return null;

  // Group results for display
  const groups: Record<string, Command[]> = {};
  for (const cmd of filtered) {
    const g = cmd.group ?? 'Other';
    if (!groups[g]) groups[g] = [];
    groups[g].push(cmd);
  }
  let globalIdx = 0;

  return (
    <div
      onClick={close}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        zIndex: 9999, display: 'flex', alignItems: 'flex-start',
        justifyContent: 'center', paddingTop: '15vh',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Command Palette"
        style={{
          background: '#111827', border: '1px solid #334155', borderRadius: 12,
          width: 560, maxWidth: '90vw', boxShadow: '0 25px 50px rgba(0,0,0,0.5)', overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ color: '#475569', marginRight: 8, fontSize: 14 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search sessions, agents, macros, commands…"
            aria-label="Command search"
            style={{
              flex: 1, background: 'none', border: 'none', outline: 'none',
              color: '#e2e8f0', fontSize: 14, fontFamily: 'inherit',
            }}
          />
          <span style={{ fontSize: 10, color: '#475569', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px' }}>Esc</span>
        </div>
        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '20px 16px', color: '#475569', fontSize: 13, textAlign: 'center' }}>
              No results for &ldquo;{query}&rdquo;
            </div>
          ) : (
            Object.entries(groups).map(([group, cmds]) => (
              <div key={group}>
                <div style={{ padding: '6px 16px 2px', fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
                  {group}
                </div>
                {cmds.map((cmd) => {
                  const i = globalIdx++;
                  return (
                    <div
                      key={cmd.id}
                      onClick={cmd.action}
                      style={{
                        padding: '9px 16px', cursor: 'pointer',
                        background: i === selected ? '#1e293b' : 'none',
                        display: 'flex', alignItems: 'center', gap: 12,
                        transition: 'background 0.1s',
                      }}
                      onMouseEnter={() => setSelected(i)}
                    >
                      <div>
                        <div style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500 }}>{cmd.label}</div>
                        {cmd.description && (
                          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{cmd.description}</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
        <div style={{ padding: '8px 16px', borderTop: '1px solid #1e293b', display: 'flex', gap: 12, fontSize: 10, color: '#475569' }}>
          <span>↑↓ navigate</span>
          <span>↵ select</span>
          <span>Esc close</span>
        </div>
      </div>
    </div>
  );
}

'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_URL } from '@/constants/api';
import type { ViewId } from '@/components/Header/Header';

interface Command {
  id: string;
  label: string;
  description?: string;
  action: () => void;
}

interface CommandPaletteProps {
  onViewChange: (view: ViewId) => void;
  onNewSession: () => void;
  sessionId: string | null;
}

export function CommandPalette({ onViewChange, onNewSession, sessionId }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Cmd+K / Ctrl+K opens the palette; Ctrl+F also opens it (search-first)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'f')) {
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
    } else {
      setQuery('');
    }
  }, [open]);

  const commands: Command[] = [
    { id: 'chat', label: 'Go to Chat', description: 'Switch to chat view', action: () => { onViewChange('chat'); setOpen(false); } },
    { id: 'analytics', label: 'Go to Analytics', description: 'Switch to analytics view', action: () => { onViewChange('analytics'); setOpen(false); } },
    { id: 'memory', label: 'Go to Memory', description: 'Inspect agent memory', action: () => { onViewChange('memory'); setOpen(false); } },
    { id: 'new-session', label: 'New Session', description: 'Start a new conversation', action: () => { onNewSession(); setOpen(false); } },
    {
      id: 'export-md',
      label: 'Export as Markdown',
      description: 'Download current chat as .md',
      action: async () => {
        if (!sessionId) return;
        setOpen(false);
        const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=md`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${sessionId}.md`;
        a.click();
        URL.revokeObjectURL(url);
      },
    },
    {
      id: 'export-json',
      label: 'Export as JSON',
      description: 'Download current chat as .json',
      action: async () => {
        if (!sessionId) return;
        setOpen(false);
        const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=json`);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${sessionId}.json`;
        a.click();
        URL.revokeObjectURL(url);
      },
    },
  ];

  const filtered = query.trim()
    ? commands.filter(
        (c) =>
          c.label.toLowerCase().includes(query.toLowerCase()) ||
          c.description?.toLowerCase().includes(query.toLowerCase()),
      )
    : commands;

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
    }
  }, [filtered, selected]);

  useEffect(() => {
    setSelected(0);
  }, [query]);

  if (!open) return null;

  return (
    <div
      onClick={() => setOpen(false)}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '15vh',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#111827',
          border: '1px solid #334155',
          borderRadius: 12,
          width: 520,
          maxWidth: '90vw',
          boxShadow: '0 25px 50px rgba(0,0,0,0.5)',
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ color: '#475569', marginRight: 8, fontSize: 14 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a command..."
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              color: '#e2e8f0',
              fontSize: 14,
              fontFamily: 'inherit',
            }}
          />
          <span style={{ fontSize: 10, color: '#475569', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px' }}>Esc</span>
        </div>
        <div style={{ maxHeight: 320, overflowY: 'auto' }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '20px 16px', color: '#475569', fontSize: 13, textAlign: 'center' }}>
              No commands match &ldquo;{query}&rdquo;
            </div>
          ) : (
            filtered.map((cmd, i) => (
              <div
                key={cmd.id}
                onClick={cmd.action}
                style={{
                  padding: '10px 16px',
                  cursor: 'pointer',
                  background: i === selected ? '#1e293b' : 'none',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
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

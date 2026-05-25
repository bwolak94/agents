'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/constants/api';

interface SessionItem {
  session_id: string;
  updated_at: string;
  created_at: string;
  preview: string;
}

interface Props {
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  refreshTrigger?: number;
}

function formatDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMs / 3600000);
  const diffD = Math.floor(diffMs / 86400000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffH < 24) return `${diffH}h ago`;
  if (diffD < 7) return `${diffD}d ago`;
  return d.toLocaleDateString();
}

export function ChatHistorySidebar({ activeSessionId, onSelect, onNew, refreshTrigger }: Props) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchSessions = useCallback(() => {
    fetch(`${API_URL}/sessions`)
      .then((r) => r.json())
      .then((d) => setSessions(d.sessions ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions, refreshTrigger]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setDeletingId(sessionId);
    await fetch(`${API_URL}/history/${sessionId}`, { method: 'DELETE' });
    setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    if (activeSessionId === sessionId) onNew();
    setDeletingId(null);
  };

  return (
    <div
      style={{
        width: 220,
        flexShrink: 0,
        borderRight: '1px solid #1a1a2e',
        display: 'flex',
        flexDirection: 'column',
        background: '#080812',
        overflow: 'hidden',
      }}
    >
      {/* Header + New Chat */}
      <div
        style={{
          padding: '12px 10px 8px',
          borderBottom: '1px solid #1a1a2e',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Chats
        </span>
        <button
          onClick={onNew}
          title="New chat"
          style={{
            background: '#1e293b',
            border: '1px solid #334155',
            borderRadius: 8,
            color: '#94a3b8',
            cursor: 'pointer',
            fontSize: 16,
            lineHeight: 1,
            padding: '3px 8px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <span style={{ fontSize: 18, lineHeight: 1 }}>+</span>
        </button>
      </div>

      {/* Session list */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sessions.length === 0 && (
          <div style={{ padding: '20px 12px', color: '#334155', fontSize: 12, textAlign: 'center' }}>
            No previous chats
          </div>
        )}
        {sessions.map((s) => {
          const isActive = s.session_id === activeSessionId;
          const isHovered = hoveredId === s.session_id;
          return (
            <div
              key={s.session_id}
              onClick={() => onSelect(s.session_id)}
              onMouseEnter={() => setHoveredId(s.session_id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                padding: '9px 10px',
                cursor: 'pointer',
                background: isActive ? '#1e293b' : isHovered ? '#0f172a' : 'transparent',
                borderLeft: isActive ? '2px solid #2563eb' : '2px solid transparent',
                position: 'relative',
                transition: 'background 0.1s',
              }}
            >
              {/* Preview text */}
              <div
                style={{
                  fontSize: 12,
                  color: isActive ? '#e2e8f0' : '#94a3b8',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  paddingRight: isHovered ? 22 : 0,
                  lineHeight: 1.4,
                }}
              >
                {s.preview}
              </div>
              {/* Timestamp */}
              <div style={{ fontSize: 10, color: '#334155', marginTop: 2 }}>
                {formatDate(s.updated_at)}
              </div>

              {/* Delete button — visible on hover */}
              {isHovered && (
                <button
                  onClick={(e) => handleDelete(e, s.session_id)}
                  disabled={deletingId === s.session_id}
                  title="Delete chat"
                  style={{
                    position: 'absolute',
                    right: 6,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#475569',
                    fontSize: 14,
                    padding: '2px 4px',
                    lineHeight: 1,
                    borderRadius: 4,
                  }}
                >
                  ×
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { API_URL } from '@/constants/api';

const PAGE_SIZE = 20;

interface SessionItem {
  session_id: string;
  updated_at: string;
  created_at: string;
  preview: string;
  tags?: string[];
}

interface Props {
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  refreshTrigger?: number;
}

function stripXml(text: string): string {
  const clean = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  return clean || text;
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

const PINNED_KEY = 'agent-pinned-sessions';
function getPinned(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(PINNED_KEY) || '[]')); } catch { return new Set(); }
}
function savePinned(pinned: Set<string>) {
  localStorage.setItem(PINNED_KEY, JSON.stringify([...pinned]));
}

export function ChatHistorySidebar({ activeSessionId, onSelect, onNew, refreshTrigger }: Props) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [skip, setSkip] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<{ session_id: string; preview?: string }[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [addingTagFor, setAddingTagFor] = useState<string | null>(null);
  const [newTag, setNewTag] = useState('');
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load pinned from localStorage
  useEffect(() => { setPinned(getPinned()); }, []);

  const togglePin = useCallback((e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) next.delete(sessionId); else next.add(sessionId);
      savePinned(next);
      return next;
    });
  }, []);

  const fetchSessions = useCallback((reset = true) => {
    const currentSkip = reset ? 0 : skip;
    const url = tagFilter
      ? `${API_URL}/sessions/by-tag/${encodeURIComponent(tagFilter)}`
      : `${API_URL}/sessions?limit=${PAGE_SIZE}&skip=${currentSkip}`;
    fetch(url)
      .then((r) => r.json())
      .then((d) => {
        const incoming: SessionItem[] = d.sessions ?? d.session_ids?.map((id: string) => ({ session_id: id, updated_at: '', created_at: '', preview: id })) ?? [];
        if (reset) { setSessions(incoming); setSkip(incoming.length); }
        else { setSessions((prev) => [...prev, ...incoming]); setSkip((s) => s + incoming.length); }
        setHasMore(incoming.length === PAGE_SIZE && !tagFilter);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagFilter]);

  useEffect(() => { fetchSessions(true); setSkip(0); }, [fetchSessions, refreshTrigger]);

  // Fetch all tags for the tag filter bar
  useEffect(() => {
    fetch(`${API_URL}/tags`).then(r => r.json()).then(d => setAllTags(d.tags ?? [])).catch(() => {});
  }, [refreshTrigger]);

  // Search with debounce
  useEffect(() => {
    if (!searchQuery.trim()) { setSearchResults(null); return; }
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await fetch(`${API_URL}/search?q=${encodeURIComponent(searchQuery)}`);
        const d = await r.json();
        setSearchResults(d.results ?? []);
      } catch { setSearchResults([]); }
      finally { setSearching(false); }
    }, 400);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [searchQuery]);

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    setDeletingId(sessionId);
    await fetch(`${API_URL}/history/${sessionId}`, { method: 'DELETE' });
    setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    if (activeSessionId === sessionId) onNew();
    setDeletingId(null);
  };

  const handleAddTag = async (sessionId: string) => {
    if (!newTag.trim()) return;
    await fetch(`${API_URL}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, tag: newTag.trim() }),
    });
    setSessions(prev => prev.map(s => s.session_id === sessionId
      ? { ...s, tags: [...(s.tags ?? []), newTag.trim().toLowerCase()] }
      : s
    ));
    setAllTags(prev => [...new Set([...prev, newTag.trim().toLowerCase()])].sort());
    setNewTag('');
    setAddingTagFor(null);
  };

  const handleRemoveTag = async (e: React.MouseEvent, sessionId: string, tag: string) => {
    e.stopPropagation();
    await fetch(`${API_URL}/tags/${sessionId}/${encodeURIComponent(tag)}`, { method: 'DELETE' });
    setSessions(prev => prev.map(s => s.session_id === sessionId
      ? { ...s, tags: (s.tags ?? []).filter(t => t !== tag) }
      : s
    ));
  };

  // Sort: pinned first, then by updated_at
  const displaySessions = searchResults
    ? searchResults.map(r => ({ session_id: r.session_id, updated_at: '', created_at: '', preview: r.preview || r.session_id }))
    : [...sessions].sort((a, b) => {
        const ap = pinned.has(a.session_id) ? 1 : 0;
        const bp = pinned.has(b.session_id) ? 1 : 0;
        return bp - ap;
      });

  const btnStyle = {
    background: 'none', border: 'none', cursor: 'pointer',
    color: '#475569', fontSize: 12, padding: '1px 3px', lineHeight: 1, borderRadius: 3,
  } as const;

  return (
    <div style={{ width: 220, flexShrink: 0, borderRight: '1px solid #1a1a2e', display: 'flex', flexDirection: 'column', background: '#080812', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '10px 10px 6px', borderBottom: '1px solid #1a1a2e', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Chats</span>
          <button onClick={onNew} title="New chat" style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '3px 8px' }}>+</button>
        </div>
        {/* Search bar */}
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search chats… (Ctrl+F)"
          style={{ width: '100%', background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, color: '#e2e8f0', fontSize: 11, padding: '5px 8px', outline: 'none', boxSizing: 'border-box' }}
        />
      </div>

      {/* Tag filter bar */}
      {allTags.length > 0 && (
        <div style={{ padding: '4px 8px', borderBottom: '1px solid #1a1a2e', display: 'flex', gap: 4, flexWrap: 'wrap', flexShrink: 0 }}>
          <button onClick={() => setTagFilter(null)} style={{ ...btnStyle, color: tagFilter === null ? '#60a5fa' : '#475569', fontSize: 10, border: '1px solid #1e293b', borderRadius: 4, padding: '2px 6px' }}>All</button>
          {allTags.slice(0, 8).map(tag => (
            <button key={tag} onClick={() => setTagFilter(tagFilter === tag ? null : tag)} style={{ ...btnStyle, color: tagFilter === tag ? '#60a5fa' : '#64748b', fontSize: 10, border: `1px solid ${tagFilter === tag ? '#2563eb' : '#1e293b'}`, borderRadius: 4, padding: '2px 6px' }}>#{tag}</button>
          ))}
        </div>
      )}

      {/* Session list */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        {searching && <div style={{ padding: '12px', color: '#475569', fontSize: 11, textAlign: 'center' }}>Searching…</div>}
        {displaySessions.length === 0 && !searching && (
          <div style={{ padding: '20px 12px', color: '#334155', fontSize: 12, textAlign: 'center' }}>
            {searchQuery ? 'No results' : 'No previous chats'}
          </div>
        )}
        {displaySessions.map((s) => {
          const isActive = s.session_id === activeSessionId;
          const isHovered = hoveredId === s.session_id;
          const isPinned = pinned.has(s.session_id);
          const fullSession = sessions.find(x => x.session_id === s.session_id);
          return (
            <div
              key={s.session_id}
              onClick={() => onSelect(s.session_id)}
              onMouseEnter={() => setHoveredId(s.session_id)}
              onMouseLeave={() => { setHoveredId(null); setAddingTagFor(null); }}
              style={{ padding: '9px 10px 6px', cursor: 'pointer', background: isActive ? '#1e293b' : isHovered ? '#0f172a' : 'transparent', borderLeft: isActive ? '2px solid #2563eb' : '2px solid transparent', position: 'relative', transition: 'background 0.1s' }}
            >
              {/* Pin indicator */}
              {isPinned && <span style={{ position: 'absolute', top: 6, right: 6, fontSize: 9, color: '#ca8a04' }}>★</span>}

              <div style={{ fontSize: 12, color: isActive ? '#e2e8f0' : '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', paddingRight: 14, lineHeight: 1.4 }}>
                {stripXml(s.preview)}
              </div>
              <div style={{ fontSize: 10, color: '#334155', marginTop: 2 }}>{formatDate(s.updated_at)}</div>

              {/* Tags */}
              {fullSession?.tags && fullSession.tags.length > 0 && (
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 4 }}>
                  {fullSession.tags.map(tag => (
                    <span key={tag} onClick={e => handleRemoveTag(e, s.session_id, tag)} title="Click to remove tag" style={{ fontSize: 9, background: '#1e293b', color: '#60a5fa', borderRadius: 3, padding: '1px 4px', cursor: 'pointer' }}>#{tag}</span>
                  ))}
                </div>
              )}

              {/* Hover actions */}
              {isHovered && (
                <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                  <button onClick={e => togglePin(e, s.session_id)} title={isPinned ? 'Unpin' : 'Pin'} style={{ ...btnStyle, color: isPinned ? '#ca8a04' : '#475569' }}>★</button>
                  <button onClick={e => { e.stopPropagation(); setAddingTagFor(addingTagFor === s.session_id ? null : s.session_id); setNewTag(''); }} title="Add tag" style={btnStyle}>#</button>
                  <button onClick={e => handleDelete(e, s.session_id)} disabled={deletingId === s.session_id} title="Delete" style={{ ...btnStyle, marginLeft: 'auto', fontSize: 14 }}>×</button>
                </div>
              )}

              {/* Inline tag input */}
              {addingTagFor === s.session_id && (
                <div onClick={e => e.stopPropagation()} style={{ marginTop: 4, display: 'flex', gap: 4 }}>
                  <input
                    autoFocus
                    value={newTag}
                    onChange={e => setNewTag(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleAddTag(s.session_id); if (e.key === 'Escape') setAddingTagFor(null); }}
                    placeholder="tag name"
                    style={{ flex: 1, fontSize: 10, background: '#0f172a', border: '1px solid #334155', borderRadius: 4, color: '#e2e8f0', padding: '2px 5px', outline: 'none' }}
                  />
                  <button onClick={() => handleAddTag(s.session_id)} style={{ ...btnStyle, color: '#60a5fa' }}>+</button>
                </div>
              )}
            </div>
          );
        })}
        {hasMore && !searchQuery && (
          <button onClick={() => fetchSessions(false)} style={{ margin: '8px 10px', background: 'none', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', cursor: 'pointer', fontSize: 11, padding: '5px 0' }}>
            Load more
          </button>
        )}
      </div>
    </div>
  );
}

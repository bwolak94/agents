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
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

function stripXml(text: string): string {
  return text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || text;
}

function formatDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMs / 3600000);
  const diffD = Math.floor(diffMs / 86400000);
  if (diffMin < 1)  return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffH < 24)   return `${diffH}h ago`;
  if (diffD < 7)    return `${diffD}d ago`;
  return d.toLocaleDateString();
}

const PINNED_KEY = 'agent-pinned-sessions';
function getPinned(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(PINNED_KEY) || '[]')); } catch { return new Set(); }
}
function savePinned(pinned: Set<string>) {
  localStorage.setItem(PINNED_KEY, JSON.stringify([...pinned]));
}

export function ChatHistorySidebar({ activeSessionId, onSelect, onNew, refreshTrigger, collapsed = false, onToggleCollapse }: Props) {
  const [sessions, setSessions]         = useState<SessionItem[]>([]);
  const [hoveredId, setHoveredId]       = useState<string | null>(null);
  const [deletingId, setDeletingId]     = useState<string | null>(null);
  const [skip, setSkip]                 = useState(0);
  const [hasMore, setHasMore]           = useState(false);
  const [pinned, setPinned]             = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery]   = useState('');
  const [searchResults, setSearchResults] = useState<{ session_id: string; preview?: string }[] | null>(null);
  const [searching, setSearching]       = useState(false);
  const [tagFilter, setTagFilter]       = useState<string | null>(null);
  const [allTags, setAllTags]           = useState<string[]>([]);
  const [addingTagFor, setAddingTagFor] = useState<string | null>(null);
  const [newTag, setNewTag]             = useState('');
  // Inline rename state
  const [renamingId, setRenamingId]     = useState<string | null>(null);
  const [renameValue, setRenameValue]   = useState('');
  // Session merge state
  const [mergingId, setMergingId]       = useState<string | null>(null);
  const [merging, setMerging]           = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Infinite scroll sentinel
  const loadMoreRef = useRef<HTMLDivElement>(null);

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
        else       { setSessions((prev) => [...prev, ...incoming]); setSkip((s) => s + incoming.length); }
        setHasMore(incoming.length === PAGE_SIZE && !tagFilter);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagFilter]);

  useEffect(() => { fetchSessions(true); setSkip(0); }, [fetchSessions, refreshTrigger]);

  useEffect(() => {
    fetch(`${API_URL}/tags`).then(r => r.json()).then(d => setAllTags(d.tags ?? [])).catch(() => {});
  }, [refreshTrigger]);

  useEffect(() => {
    if (!searchQuery.trim()) { setSearchResults(null); return; }
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r  = await fetch(`${API_URL}/search?q=${encodeURIComponent(searchQuery)}`);
        const d  = await r.json();
        setSearchResults(d.results ?? []);
      } catch { setSearchResults([]); }
      finally   { setSearching(false); }
    }, 400);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [searchQuery]);

  // Infinite scroll via IntersectionObserver
  useEffect(() => {
    if (!loadMoreRef.current || !hasMore || searchQuery || tagFilter) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) fetchSessions(false);
      },
      { threshold: 0.1 },
    );
    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [hasMore, searchQuery, tagFilter, fetchSessions]);

  // Optimistic delete with rollback on error
  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    const snapshot = sessions;
    // Optimistic update
    setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    if (activeSessionId === sessionId) onNew();
    setDeletingId(sessionId);
    try {
      const res = await fetch(`${API_URL}/history/${sessionId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
    } catch {
      // Rollback
      setSessions(snapshot);
    } finally {
      setDeletingId(null);
    }
  };

  // Inline session rename
  const handleStartRename = (e: React.MouseEvent, sessionId: string, currentTitle: string) => {
    e.stopPropagation();
    setRenamingId(sessionId);
    setRenameValue(currentTitle || '');
  };

  const handleRename = async (sessionId: string) => {
    const title = renameValue.trim();
    const snapshot = sessions;
    // Optimistic update
    setSessions(prev => prev.map(s => s.session_id === sessionId ? { ...s, preview: title || s.preview } : s));
    setRenamingId(null);
    if (!title) return;
    try {
      const res = await fetch(`${API_URL}/sessions/${sessionId}/title`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error('Rename failed');
    } catch {
      setSessions(snapshot);
    }
  };

  const handleAddTag = async (sessionId: string) => {
    if (!newTag.trim()) return;
    await fetch(`${API_URL}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, tag: newTag.trim() }),
    });
    setSessions(prev => prev.map(s => s.session_id === sessionId ? { ...s, tags: [...(s.tags ?? []), newTag.trim().toLowerCase()] } : s));
    setAllTags(prev => [...new Set([...prev, newTag.trim().toLowerCase()])].sort());
    setNewTag('');
    setAddingTagFor(null);
  };

  const handleMerge = async (sourceId: string) => {
    if (!activeSessionId || sourceId === activeSessionId) return;
    setMerging(true);
    // F24 — optimistic remove of the merged-away session so UI updates immediately
    const snapshot = sessions;
    setSessions(prev => prev.filter(s => s.session_id !== sourceId));
    try {
      const res = await fetch(`${API_URL}/sessions/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_session_id: sourceId,
          target_session_id: activeSessionId,
          deduplicate: true,
        }),
      });
      if (!res.ok) throw new Error('Merge failed');
    } catch {
      setSessions(snapshot);  // F24 — rollback on error
    }
    setMergingId(null);
    setMerging(false);
  };

  const handleRemoveTag = async (e: React.MouseEvent, sessionId: string, tag: string) => {
    e.stopPropagation();
    await fetch(`${API_URL}/tags/${sessionId}/${encodeURIComponent(tag)}`, { method: 'DELETE' });
    setSessions(prev => prev.map(s => s.session_id === sessionId ? { ...s, tags: (s.tags ?? []).filter(t => t !== tag) } : s));
  };

  const displaySessions = searchResults
    ? searchResults.map(r => ({ session_id: r.session_id, updated_at: '', created_at: '', preview: r.preview || r.session_id }))
    : [...sessions].sort((a, b) => (pinned.has(b.session_id) ? 1 : 0) - (pinned.has(a.session_id) ? 1 : 0));

  // #20 — collapsed view
  if (collapsed) {
    return (
      <div className="w-8 flex-shrink-0 border-r border-border-dim bg-[#080812] flex flex-col items-center pt-3">
        <button onClick={onToggleCollapse} title="Expand sidebar" aria-label="Expand sidebar"
          className="text-text-ghost hover:text-text-faint transition-colors text-lg">›</button>
      </div>
    );
  }

  return (
    <div className="w-[220px] flex-shrink-0 border-r border-border-dim flex flex-col bg-[#080812] overflow-hidden">
      {/* Header */}
      <div className="px-2.5 pt-2.5 pb-1.5 border-b border-border-dim flex-shrink-0">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] font-semibold text-text-faint uppercase tracking-wider">Chats</span>
          <div className="flex items-center gap-1">
            <button onClick={onNew} title="New chat" aria-label="New chat"
              className="bg-surface-active border border-border-strong rounded-lg text-text-secondary text-base px-2 py-0.5 hover:text-text-primary transition-colors">
              +
            </button>
            {/* #20 — collapse button */}
            {onToggleCollapse && (
              <button onClick={onToggleCollapse} title="Collapse sidebar" aria-label="Collapse sidebar"
                className="text-text-ghost hover:text-text-faint transition-colors text-base leading-none px-1">
                ‹
              </button>
            )}
          </div>
        </div>
        <input
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder="Search chats… (Ctrl+F)"
          className="w-full bg-surface-hover border border-border-base rounded text-text-primary text-[11px] px-2 py-1 outline-none focus:border-border-strong transition-colors"
        />
      </div>

      {/* Tag filter bar */}
      {allTags.length > 0 && (
        <div className="px-2 py-1 border-b border-border-dim flex gap-1 flex-wrap flex-shrink-0">
          <button onClick={() => setTagFilter(null)}
            className={`text-[10px] border rounded px-1.5 py-0.5 transition-colors ${tagFilter === null ? 'border-accent-blue text-accent-blue-light' : 'border-border-base text-text-faint hover:text-text-muted'}`}>
            All
          </button>
          {allTags.slice(0, 8).map(tag => (
            <button key={tag} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
              className={`text-[10px] border rounded px-1.5 py-0.5 transition-colors ${tagFilter === tag ? 'border-accent-blue text-accent-blue-light' : 'border-border-base text-text-faint hover:text-text-muted'}`}>
              #{tag}
            </button>
          ))}
        </div>
      )}

      {/* Session list */}
      <div className="flex-1 overflow-y-auto flex flex-col">
        {searching && <div className="px-3 py-3 text-[11px] text-text-faint text-center">Searching…</div>}
        {displaySessions.length === 0 && !searching && (
          <div className="px-3 py-5 text-xs text-border-strong text-center">
            {searchQuery ? 'No results' : 'No previous chats'}
          </div>
        )}
        {displaySessions.map((s) => {
          const isActive  = s.session_id === activeSessionId;
          const isHovered = hoveredId === s.session_id;
          const isPinned  = pinned.has(s.session_id);
          const full      = sessions.find(x => x.session_id === s.session_id);
          return (
            <div
              key={s.session_id}
              onClick={() => onSelect(s.session_id)}
              onMouseEnter={() => setHoveredId(s.session_id)}
              onMouseLeave={() => { setHoveredId(null); setAddingTagFor(null); }}
              className={`px-2.5 py-2 cursor-pointer relative transition-colors border-l-2
                ${isActive ? 'bg-surface-active border-l-accent-blue' : isHovered ? 'bg-surface-hover border-l-transparent' : 'border-l-transparent'}`}
            >
              {isPinned && <span className="absolute top-1.5 right-1.5 text-[9px] text-accent-yellow">★</span>}
              <div className={`text-xs truncate pr-3 leading-snug ${isActive ? 'text-text-primary' : 'text-text-secondary'}`}>
                {stripXml(s.preview)}
              </div>
              <div className="text-[10px] text-border-strong mt-0.5">{formatDate(s.updated_at)}</div>

              {full?.tags && full.tags.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-1">
                  {full.tags.map(tag => (
                    <span key={tag} onClick={e => handleRemoveTag(e, s.session_id, tag)}
                      className="text-[9px] bg-surface-active text-accent-blue-light rounded px-1 py-0.5 cursor-pointer hover:bg-surface-hover transition-colors">
                      #{tag}
                    </span>
                  ))}
                </div>
              )}

              {/* Inline rename input */}
              {mergingId === s.session_id ? (
                <div onClick={e => e.stopPropagation()} className="mt-1 flex flex-col gap-1">
                  <p className="text-[9px] text-text-faint">Merge this session into active?</p>
                  <div className="flex gap-1">
                    <button onClick={() => handleMerge(s.session_id)} disabled={merging}
                      className="text-[9px] bg-accent-blue text-white rounded px-1.5 py-0.5 hover:bg-blue-600 transition-colors disabled:opacity-50">
                      {merging ? '…' : 'Merge'}
                    </button>
                    <button onClick={() => setMergingId(null)}
                      className="text-[9px] text-text-faint hover:text-text-muted transition-colors px-1">Cancel</button>
                  </div>
                </div>
              ) : renamingId === s.session_id ? (
                <div onClick={e => e.stopPropagation()} className="mt-1 flex gap-1">
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={e => setRenameValue(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') handleRename(s.session_id);
                      if (e.key === 'Escape') setRenamingId(null);
                    }}
                    onBlur={() => handleRename(s.session_id)}
                    placeholder="Session name"
                    className="flex-1 text-[10px] bg-surface-hover border border-border-strong rounded px-1.5 py-0.5 text-text-primary outline-none"
                  />
                </div>
              ) : isHovered && (
                <div className="flex gap-1 mt-1 items-center">
                  <button onClick={e => togglePin(e, s.session_id)} title={isPinned ? 'Unpin' : 'Pin'}
                    className={`text-xs px-0.5 hover:opacity-100 transition-opacity ${isPinned ? 'text-accent-yellow' : 'text-text-faint opacity-60'}`}>★</button>
                  <button onClick={e => handleStartRename(e, s.session_id, s.preview)} title="Rename"
                    className="text-xs text-text-faint opacity-60 hover:opacity-100 transition-opacity px-0.5">✎</button>
                  <button onClick={e => { e.stopPropagation(); setAddingTagFor(addingTagFor === s.session_id ? null : s.session_id); setNewTag(''); }}
                    className="text-xs text-text-faint opacity-60 hover:opacity-100 transition-opacity px-0.5">#</button>
                  {s.session_id !== activeSessionId && (
                    <button onClick={e => { e.stopPropagation(); setMergingId(s.session_id); }} title="Merge into active session"
                      className="text-xs text-text-faint opacity-60 hover:opacity-100 transition-opacity px-0.5">⤵</button>
                  )}
                  <button onClick={e => handleDelete(e, s.session_id)} disabled={deletingId === s.session_id}
                    className="text-sm text-text-faint opacity-60 hover:opacity-100 hover:text-red-400 transition-all ml-auto px-0.5">×</button>
                </div>
              )}

              {addingTagFor === s.session_id && (
                <div onClick={e => e.stopPropagation()} className="mt-1 flex gap-1">
                  <input autoFocus value={newTag} onChange={e => setNewTag(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleAddTag(s.session_id); if (e.key === 'Escape') setAddingTagFor(null); }}
                    placeholder="tag name"
                    className="flex-1 text-[10px] bg-surface-hover border border-border-strong rounded px-1.5 py-0.5 text-text-primary outline-none" />
                  <button onClick={() => handleAddTag(s.session_id)}
                    className="text-[10px] text-accent-blue-light hover:text-accent-blue transition-colors px-1">+</button>
                </div>
              )}
            </div>
          );
        })}
        {/* Infinite scroll sentinel (replaces Load more button) */}
        {hasMore && !searchQuery && !tagFilter && (
          <div ref={loadMoreRef} className="h-4" aria-hidden="true" />
        )}
      </div>
    </div>
  );
}

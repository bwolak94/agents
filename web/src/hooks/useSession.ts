'use client';
import { useState, useEffect, useCallback } from 'react';

// Must match server-side _SESSION_ID_RE: ^[a-zA-Z0-9_\-]{1,64}$
const SESSION_ID_RE = /^[a-zA-Z0-9_\-]{1,64}$/;

function generateId(): string {
  // crypto.randomUUID() is available in all modern browsers and Node 15+
  const raw = typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID().replace(/-/g, '')
    : Math.random().toString(36).slice(2, 18);
  return `session-${raw}`;
}

function isValidSessionId(id: string): boolean {
  return SESSION_ID_RE.test(id);
}

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    let sid = localStorage.getItem('agent_session_id');
    // Discard stored IDs that don't match the server validation regex (#13)
    if (!sid || !isValidSessionId(sid)) {
      sid = generateId();
      localStorage.setItem('agent_session_id', sid);
    }
    setSessionId(sid);
  }, []);

  const switchSession = useCallback((id: string) => {
    localStorage.setItem('agent_session_id', id);
    setSessionId(id);
  }, []);

  const newSession = useCallback(() => {
    const id = generateId();
    localStorage.setItem('agent_session_id', id);
    setSessionId(id);
    return id;
  }, []);

  return { sessionId, switchSession, newSession };
}

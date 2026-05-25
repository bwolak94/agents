'use client';
import { useState, useEffect, useCallback } from 'react';

function generateId() {
  return 'session-' + Math.random().toString(36).slice(2, 10);
}

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    let sid = localStorage.getItem('agent_session_id');
    if (!sid) {
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

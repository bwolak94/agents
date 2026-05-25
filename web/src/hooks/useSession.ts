'use client';
import { useState, useEffect } from 'react';

export function useSession(): string | null {
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    let sid = localStorage.getItem('agent_session_id');
    if (!sid) {
      sid = 'session-' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem('agent_session_id', sid);
    }
    setSessionId(sid);
  }, []);

  return sessionId;
}

'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/constants/api';

export interface Prompt {
  prompt_id: string;
  title: string;
  content: string;
  tags: string[];
  created_at: string;
}

interface UsePromptsResult {
  prompts: Prompt[];
  loading: boolean;
  savePrompt: (title: string, content: string, tags: string[]) => Promise<void>;
  deletePrompt: (prompt_id: string) => Promise<void>;
}

const GLOBAL_SESSION = 'default';

async function fetchSession(session: string): Promise<Prompt[]> {
  const r = await fetch(`${API_URL}/prompts/${session}`);
  if (!r.ok) return [];
  const d = (await r.json()) as { prompts: Prompt[] };
  return d.prompts ?? [];
}

export function usePrompts(sessionId: string | null): UsePromptsResult {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchPrompts = useCallback(() => {
    setLoading(true);
    // Always fetch global "default" library + current session prompts (merged, deduped)
    const sessions = [GLOBAL_SESSION];
    if (sessionId && sessionId !== GLOBAL_SESSION) sessions.push(sessionId);

    Promise.all(sessions.map(fetchSession))
      .then((results) => {
        const seen = new Set<string>();
        const merged: Prompt[] = [];
        // Current session first (personal prompts on top), then global
        for (const list of [...results].reverse()) {
          for (const p of list) {
            if (!seen.has(p.prompt_id)) {
              seen.add(p.prompt_id);
              merged.push(p);
            }
          }
        }
        setPrompts(merged);
      })
      .catch(() => setPrompts([]))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  const savePrompt = useCallback(
    async (title: string, content: string, tags: string[]): Promise<void> => {
      if (!sessionId) return;
      await fetch(`${API_URL}/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, title, content, tags }),
      });
      fetchPrompts();
    },
    [sessionId, fetchPrompts],
  );

  const deletePrompt = useCallback(
    async (prompt_id: string): Promise<void> => {
      if (!sessionId) return;
      await fetch(`${API_URL}/prompts/${sessionId}/${prompt_id}`, {
        method: 'DELETE',
      });
      setPrompts((prev) => prev.filter((p) => p.prompt_id !== prompt_id));
    },
    [sessionId],
  );

  return { prompts, loading, savePrompt, deletePrompt };
}

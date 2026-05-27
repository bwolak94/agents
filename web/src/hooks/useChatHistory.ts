'use client';
import { useState, useEffect } from 'react';
import type { ChatMessage } from '@/types/chat';
import { API_URL } from '@/constants/api';

interface HistoryResponse {
  messages?: Array<{
    role: string;
    content: string;
    model?: string;
    agent?: string;
    tools?: string[];
  }>;
}

export function useChatHistory(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    fetch(`${API_URL}/history/${sessionId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: HistoryResponse) => {
        setMessages(
          (data.messages ?? []).map((m) => ({
            role: m.role as ChatMessage['role'],
            content: m.content,
            model: m.model,
            agent: m.agent,
            tools: m.tools,
          })),
        );
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load history');
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  return { messages, setMessages, historyLoading: loading, historyError: error };
}

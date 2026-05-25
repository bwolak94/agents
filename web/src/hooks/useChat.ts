'use client';
import { useState } from 'react';
import type { ChatMessage } from '@/types/chat';
import { API_URL } from '@/constants/api';

interface ChatApiResponse {
  response: string;
  model_used?: string;
  agent_used?: string;
  tools_used?: string[];
  reasoning?: string;
}

export function useChat(sessionId: string | null) {
  const [loading, setLoading] = useState(false);

  const send = async (text: string): Promise<ChatMessage> => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId, show_routing: false }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ChatApiResponse;
      return {
        role: 'assistant',
        content: data.response,
        model: data.model_used,
        agent: data.agent_used,
        tools: data.tools_used,
        reasoning: data.reasoning,
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      return { role: 'error', content: `Error: ${message}` };
    } finally {
      setLoading(false);
    }
  };

  return { loading, send };
}

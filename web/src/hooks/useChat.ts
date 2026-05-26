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

const CHAT_TIMEOUT_MS = 120_000;

export function useChat(sessionId: string | null) {
  const [loading, setLoading] = useState(false);

  const send = async (text: string): Promise<ChatMessage> => {
    setLoading(true);
    // #19 — AbortController with 120s timeout
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);

    try {
      // #20 — send request_id for backend idempotency
      const requestId = crypto.randomUUID();
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          show_routing: false,
          request_id: requestId,
        }),
        signal: controller.signal,
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
      if (err instanceof DOMException && err.name === 'AbortError') {
        return { role: 'error', content: 'Request timed out after 2 minutes. Please try again.' };
      }
      const message = err instanceof Error ? err.message : 'Unknown error';
      return { role: 'error', content: `Error: ${message}` };
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  };

  return { loading, send };
}

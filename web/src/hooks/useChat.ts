'use client';
import { useState, useRef, useEffect } from 'react';
import type { ChatMessage } from '@/types/chat';
import { API_URL } from '@/constants/api';

interface ChatApiResponse {
  response: string;
  model_used?: string;
  agent_used?: string;
  tools_used?: string[];
  reasoning?: string;
}

// F25 — typed options for send() so callers can override model, eval, etc.
export interface ChatOptions {
  preferredModel?: string;
  enableSelfEval?: boolean;
  showScratchpad?: boolean;
  systemPrompt?: string;
}

const CHAT_TIMEOUT_MS = 120_000;

export function useChat(sessionId: string | null) {
  const [loading, setLoading] = useState(false);
  // Streaming partial content — consumers can read this for live display
  const [streamingContent, setStreamingContent] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const send = async (text: string, options?: ChatOptions): Promise<ChatMessage> => {  // F25
    setLoading(true);
    setStreamingContent('');
    const controller = new AbortController();
    abortRef.current = controller;
    const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);

    try {
      const requestId = crypto.randomUUID();
      // F30 — thread X-Request-ID + Idempotency-Key through all fetch calls
      const baseHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
      };

      // Try SSE streaming endpoint first
      const streamRes = await fetch(`${API_URL}/chat/stream`, {
        method: 'POST',
        headers: baseHeaders,
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          show_routing: false,
          request_id: requestId,
          preferred_model: options?.preferredModel,     // F25
          enable_self_eval: options?.enableSelfEval,    // F25
          show_scratchpad: options?.showScratchpad,     // F25
          system_prompt: options?.systemPrompt,         // F20
        }),
        signal: controller.signal,
      });

      if (streamRes.ok && streamRes.body) {
        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder();
        let routingInfo: { model?: string; agent?: string; tools?: string[] } = {};
        let fullContent = '';
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') break;
            try {
              const evt = JSON.parse(raw) as { type: string; model?: string; agent?: string; tools?: string[]; content?: string; token?: string };
              if (evt.type === 'routing') {
                routingInfo = { model: evt.model, agent: evt.agent, tools: evt.tools };
              } else if (evt.type === 'token') {
                // Token-by-token streaming (future enhancement)
                fullContent += evt.token ?? '';
                setStreamingContent(fullContent);
              } else if (evt.type === 'response') {
                fullContent = evt.content ?? '';
                setStreamingContent(fullContent);
              }
            } catch {
              // ignore parse errors
            }
          }
        }

        setStreamingContent('');
        return {
          role: 'assistant',
          content: fullContent,
          model: routingInfo.model,
          agent: routingInfo.agent,
          tools: routingInfo.tools,
        };
      }

      // Fallback: non-streaming POST with F16 exponential backoff on network errors
      let res: Response | undefined;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          res = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: baseHeaders,
            body: JSON.stringify({
              message: text,
              session_id: sessionId,
              show_routing: false,
              request_id: requestId,
              preferred_model: options?.preferredModel,
              enable_self_eval: options?.enableSelfEval,
              show_scratchpad: options?.showScratchpad,
              system_prompt: options?.systemPrompt,  // F20 — wire through to backend
            }),
            signal: controller.signal,
          });
          break;  // success — exit retry loop
        } catch (fetchErr) {
          // F16 — retry only on network-level TypeError (not 4xx/5xx)
          if (fetchErr instanceof TypeError && attempt < 2) {
            await new Promise(r => setTimeout(r, 500 * 2 ** attempt));
            continue;
          }
          throw fetchErr;
        }
      }
      if (!res) throw new Error('No response after retries');
      if (!res.ok) throw new Error(`HTTP ${res.status} (request-id: ${requestId})`);  // F30
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
      setStreamingContent('');
      if (err instanceof DOMException && err.name === 'AbortError') {
        return { role: 'error', content: 'Request timed out after 2 minutes. Please try again.' };
      }
      const message = err instanceof Error ? err.message : 'Unknown error';
      return { role: 'error', content: `Error: ${message}` };
    } finally {
      clearTimeout(timer);
      abortRef.current = null;
      setLoading(false);
    }
  };

  const abort = () => abortRef.current?.abort();

  // #39 — cancel any in-flight request when the component unmounts
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  return { loading, send, abort, streamingContent };
}

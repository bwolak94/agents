'use client';
import { useState, useRef, useEffect, type KeyboardEvent } from 'react';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import { AGENT_CFG, DEFAULT_AGENT_CFG, MODEL_COLORS } from '@/constants/agents';
import { useChat } from '@/hooks/useChat';

interface ChatViewProps {
  sessionId: string | null;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
}

const THINKING_DOTS = [0, 1, 2];

export function ChatView({ sessionId, messages, setMessages }: ChatViewProps) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const { loading, send } = useChat(sessionId);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');

    const response = await send(text);
    setMessages((prev) => [...prev, response]);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#475569', marginTop: 60 }}>
            <div style={{ fontSize: 48 }}>🧠</div>
            <p style={{ marginTop: 12, color: '#64748b' }}>How can I help you?</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {loading && <ThinkingIndicator />}
        <div ref={bottomRef} />
      </div>

      <ChatInput
        value={input}
        loading={loading}
        onChange={setInput}
        onKeyDown={handleKeyDown}
        onSend={handleSend}
      />
    </div>
  );
}

function MessageBubble({ message: msg }: { message: ChatMessage }) {
  const agentCfg = (name?: string) => (name ? (AGENT_CFG[name] ?? DEFAULT_AGENT_CFG) : DEFAULT_AGENT_CFG);
  const isUser = msg.role === 'user';
  const isError = msg.role === 'error';

  const bubbleBg = isUser ? '#1d4ed8' : isError ? '#450a0a' : '#1e1e2e';
  const bubbleColor = isError ? '#fca5a5' : '#e2e8f0';

  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{ maxWidth: '75%' }}>
        {msg.role === 'assistant' && msg.model && (
          <div
            style={{
              display: 'flex',
              gap: 8,
              marginBottom: 4,
              fontSize: 11,
              color: '#475569',
              alignItems: 'center',
            }}
          >
            <span style={{ color: MODEL_COLORS[msg.model] ?? '#94a3b8' }}>◆ {msg.model}</span>
            <span>
              {agentCfg(msg.agent).icon} {msg.agent}
            </span>
            {msg.tools && msg.tools.length > 0 && (
              <span style={{ color: '#ca8a04' }}>🔧 {msg.tools.join(', ')}</span>
            )}
          </div>
        )}
        <div
          style={{
            borderRadius: 14,
            padding: '10px 14px',
            fontSize: 13,
            lineHeight: 1.6,
            background: bubbleBg,
            color: bubbleColor,
            borderBottomRightRadius: isUser ? 4 : 14,
            borderBottomLeftRadius: isUser ? 14 : 4,
          }}
        >
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
            {msg.content}
          </pre>
        </div>
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div style={{ display: 'flex' }}>
      <div
        style={{
          background: '#1e1e2e',
          borderRadius: 14,
          borderBottomLeftRadius: 4,
          padding: '10px 14px',
        }}
      >
        <div style={{ display: 'flex', gap: 4 }}>
          {THINKING_DOTS.map((i) => (
            <div
              key={i}
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: '#475569',
                animation: `dotBounce 1.2s ease-in-out ${i * 0.15}s infinite`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface ChatInputProps {
  value: string;
  loading: boolean;
  onChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
}

function ChatInput({ value, loading, onChange, onKeyDown, onSend }: ChatInputProps) {
  const isDisabled = loading || !value.trim();

  return (
    <div style={{ padding: '12px 16px', background: '#0a0a1a', borderTop: '1px solid #1e1e2e' }}>
      <div style={{ display: 'flex', gap: 8, maxWidth: 800, margin: '0 auto' }}>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question... (Enter to send)"
          rows={1}
          style={{
            flex: 1,
            background: '#1e1e2e',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: 12,
            padding: '10px 14px',
            fontSize: 13,
            resize: 'none',
            outline: 'none',
            fontFamily: 'inherit',
          }}
        />
        <button
          onClick={onSend}
          disabled={isDisabled}
          style={{
            background: isDisabled ? '#1e293b' : '#2563eb',
            color: '#e2e8f0',
            border: 'none',
            borderRadius: 12,
            padding: '10px 18px',
            cursor: isDisabled ? 'not-allowed' : 'pointer',
            fontSize: 16,
            transition: 'background 0.2s',
          }}
        >
          ↑
        </button>
      </div>
    </div>
  );
}

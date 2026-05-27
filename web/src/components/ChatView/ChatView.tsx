'use client';
import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import { AGENT_CFG, DEFAULT_AGENT_CFG, MODEL_COLORS } from '@/constants/agents';
import { useChat } from '@/hooks/useChat';
import { FileUpload } from '@/components/FileUpload/FileUpload';
import { VoiceInput } from '@/components/VoiceInput/VoiceInput';
import { PromptLibrary } from '@/components/PromptLibrary/PromptLibrary';
import { API_URL } from '@/constants/api';

interface ChatViewProps {
  sessionId: string | null;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  historyLoading?: boolean;
  onClearChat?: () => void;
}

const THINKING_DOTS = [0, 1, 2];

export function ChatView({ sessionId, messages, setMessages, historyLoading, onClearChat }: ChatViewProps) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const { loading, send, streamingContent } = useChat(sessionId);

  const handleExport = useCallback(async (format: 'json' | 'md') => {
    if (!sessionId) return;
    const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=${format}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sessionId}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');

    const response = await send(text);
    setMessages((prev) => [...prev, response]);
  }, [input, loading, send, setMessages]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileUploaded = (reference: string, _filename: string) => {
    setInput((prev) => (prev ? `${prev} ${reference}` : reference));
  };

  // #18 — memoized so VoiceInput doesn't re-create SpeechRecognition on every render
  const handleTranscript = useCallback((text: string) => {
    setInput(text);
  }, []);

  const handleSelectPrompt = useCallback((content: string) => {
    setInput(content);
  }, []);

  const isEmpty = messages.length === 0;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Chat header with clear + export buttons */}
      {(messages.length > 0 || onClearChat) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: 6,
            padding: '6px 16px',
            borderBottom: '1px solid #1a1a2e',
            flexShrink: 0,
          }}
        >
          {messages.length > 0 && (
            <>
              <button
                onClick={() => handleExport('md')}
                title="Export as Markdown"
                style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, color: '#475569', cursor: 'pointer', fontSize: 11, padding: '3px 10px' }}
              >
                Export .md
              </button>
              <button
                onClick={() => handleExport('json')}
                title="Export as JSON"
                style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, color: '#475569', cursor: 'pointer', fontSize: 11, padding: '3px 10px' }}
              >
                Export .json
              </button>
            </>
          )}
          {messages.length > 0 && onClearChat && (
            <button
              onClick={onClearChat}
              title="Clear chat history"
              style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, color: '#475569', cursor: 'pointer', fontSize: 11, padding: '3px 10px' }}
            >
              Clear chat
            </button>
          )}
        </div>
      )}

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
        {/* #17 — loading skeleton while history fetches */}
        {historyLoading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '20px 0' }}>
            {[80, 55, 95, 65].map((w, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: i % 2 === 0 ? 'flex-end' : 'flex-start',
                }}
              >
                <div
                  style={{
                    width: `${w}%`,
                    height: 40,
                    borderRadius: 14,
                    background: 'linear-gradient(90deg, #1a1a2e 25%, #1e293b 50%, #1a1a2e 75%)',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 1.5s infinite',
                  }}
                />
              </div>
            ))}
          </div>
        )}

        {!historyLoading && isEmpty && (
          <div style={{ textAlign: 'center', color: '#475569', marginTop: 60 }}>
            <div style={{ fontSize: 48 }}>🧠</div>
            <p style={{ marginTop: 12, color: '#64748b' }}>How can I help you?</p>
          </div>
        )}

        {!historyLoading && messages.map((msg, i) => (
          <MessageBubble
            key={`${msg.role}-${i}-${msg.content.slice(0, 20)}`}
            message={msg}
            messageIdx={i}
            sessionId={sessionId}
            onRetry={msg.role === 'assistant' ? async () => {
              // Find the preceding user message and resend it
              const userMsg = messages.slice(0, i).reverse().find(m => m.role === 'user');
              if (!userMsg || loading) return;
              const response = await send(userMsg.content);
              setMessages((prev) => [...prev, response]);
            } : undefined}
          />
        ))}

        {loading && !streamingContent && <ThinkingIndicator />}
        {loading && streamingContent && (
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <div style={{ maxWidth: '75%', background: '#1e1e2e', borderRadius: 14, borderBottomLeftRadius: 4, padding: '10px 14px', fontSize: 13, color: '#e2e8f0', lineHeight: 1.6 }}>
              <div style={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap' }}>{streamingContent}<span style={{ display: 'inline-block', width: 8, height: 14, background: '#475569', borderRadius: 2, marginLeft: 2, animation: 'dotBounce 1s ease-in-out infinite', verticalAlign: 'middle' }} /></div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <ChatInput
        value={input}
        loading={loading}
        sessionId={sessionId}
        onChange={setInput}
        onKeyDown={handleKeyDown}
        onSend={handleSend}
        onFileUploaded={handleFileUploaded}
        onTranscript={handleTranscript}
        onSelectPrompt={handleSelectPrompt}
      />
    </div>
  );
}

import type { Components } from 'react-markdown';

// #21 — markdown renderer styles
const mdComponents: Components = {
  code({ className, children, ...props }) {
    const isBlock = String(children).includes('\n');
    if (!isBlock) {
      return (
        <code
          style={{
            background: '#0d0d1a',
            border: '1px solid #334155',
            borderRadius: 4,
            padding: '1px 5px',
            fontSize: '0.9em',
            fontFamily: 'monospace',
          }}
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <pre
        style={{
          background: '#0d0d1a',
          border: '1px solid #334155',
          borderRadius: 8,
          padding: '12px 14px',
          overflowX: 'auto',
          margin: '8px 0',
          fontSize: 12,
          fontFamily: 'monospace',
          lineHeight: 1.5,
        }}
      >
        <code className={className} {...props}>
          {children}
        </code>
      </pre>
    );
  },
  p({ children }) {
    return <p style={{ margin: '6px 0', lineHeight: 1.6 }}>{children}</p>;
  },
  ul({ children }) {
    return <ul style={{ margin: '6px 0', paddingLeft: 20 }}>{children}</ul>;
  },
  ol({ children }) {
    return <ol style={{ margin: '6px 0', paddingLeft: 20 }}>{children}</ol>;
  },
  li({ children }) {
    return <li style={{ marginBottom: 4 }}>{children}</li>;
  },
  blockquote({ children }) {
    return (
      <blockquote
        style={{
          borderLeft: '3px solid #334155',
          margin: '8px 0',
          paddingLeft: 12,
          color: '#94a3b8',
        }}
      >
        {children}
      </blockquote>
    );
  },
  h1({ children }) { return <h1 style={{ fontSize: 18, margin: '12px 0 6px', color: '#e2e8f0' }}>{children}</h1>; },
  h2({ children }) { return <h2 style={{ fontSize: 16, margin: '10px 0 4px', color: '#e2e8f0' }}>{children}</h2>; },
  h3({ children }) { return <h3 style={{ fontSize: 14, margin: '8px 0 4px', color: '#e2e8f0' }}>{children}</h3>; },
};

interface MessageBubbleProps {
  message: ChatMessage;
  messageIdx: number;
  sessionId: string | null;
  onRetry?: () => void;
}

function MessageBubble({ message: msg, messageIdx, sessionId, onRetry }: MessageBubbleProps) {
  const agentCfg = (name?: string) => (name ? (AGENT_CFG[name] ?? DEFAULT_AGENT_CFG) : DEFAULT_AGENT_CFG);
  const isUser = msg.role === 'user';
  const isError = msg.role === 'error';
  const [rating, setRating] = useState<1 | -1 | null>(null);

  const bubbleBg = isUser ? '#1d4ed8' : isError ? '#450a0a' : '#1e1e2e';
  const bubbleColor = isError ? '#fca5a5' : '#e2e8f0';

  const handleFeedback = useCallback(async (r: 1 | -1) => {
    if (!sessionId) return;
    const next = rating === r ? null : r;
    setRating(next);
    if (next !== null) {
      await fetch(`${API_URL}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message_idx: messageIdx, rating: next }),
      }).catch(() => {});
    }
  }, [sessionId, messageIdx, rating]);

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
          {isUser || isError ? (
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
              {msg.content}
            </pre>
          ) : (
            <div style={{ fontFamily: 'inherit' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {msg.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {/* Feedback + Retry + TTS controls for assistant messages */}
        {msg.role === 'assistant' && (
          <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
            <button onClick={() => handleFeedback(1)} title="Helpful" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, opacity: rating === 1 ? 1 : 0.35, padding: '2px 4px', transition: 'opacity 0.15s' }}>👍</button>
            <button onClick={() => handleFeedback(-1)} title="Not helpful" style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, opacity: rating === -1 ? 1 : 0.35, padding: '2px 4px', transition: 'opacity 0.15s' }}>👎</button>
            <TtsButton text={msg.content} />
            {onRetry && (
              <button onClick={onRetry} title="Retry" style={{ background: 'none', border: '1px solid #334155', borderRadius: 4, color: '#64748b', cursor: 'pointer', fontSize: 10, padding: '2px 6px', marginLeft: 4 }}>↺ retry</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── TTS Button ───────────────────────────────────────────────────────────────
function TtsButton({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);

  const toggle = useCallback(() => {
    if (!window.speechSynthesis) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    // Strip markdown/XML for cleaner speech
    const clean = text.replace(/[#*`_\[\]<>]/g, '').slice(0, 3000);
    const utt = new SpeechSynthesisUtterance(clean);
    utt.onend = () => setSpeaking(false);
    utt.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utt);
    setSpeaking(true);
  }, [text, speaking]);

  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;

  return (
    <button onClick={toggle} title={speaking ? 'Stop reading' : 'Read aloud'} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, opacity: 0.5, padding: '2px 4px', transition: 'opacity 0.15s' }}>
      {speaking ? '⏹' : '🔊'}
    </button>
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
  sessionId: string | null;
  onChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onFileUploaded: (reference: string, filename: string) => void;
  onTranscript: (text: string) => void;
  onSelectPrompt: (content: string) => void;
}

function ChatInput({
  value,
  loading,
  sessionId,
  onChange,
  onKeyDown,
  onSend,
  onFileUploaded,
  onTranscript,
  onSelectPrompt,
}: ChatInputProps) {
  const isDisabled = loading || !value.trim();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 300)}px`;
  }, [value]);

  return (
    <div style={{ padding: '12px 16px', background: '#0a0a1a', borderTop: '1px solid #1e1e2e' }}>
      <div style={{ display: 'flex', gap: 8, maxWidth: 800, margin: '0 auto', alignItems: 'flex-end' }}>
        {/* Left controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, paddingBottom: 2 }}>
          <FileUpload sessionId={sessionId} onUploaded={onFileUploaded} />
        </div>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question... (Enter to send, Shift+Enter for new line)"
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
            lineHeight: 1.6,
            overflowY: 'auto',
            minHeight: 42,
            maxHeight: 300,
          }}
        />

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, paddingBottom: 2 }}>
          <PromptLibrary
            sessionId={sessionId}
            onSelectPrompt={onSelectPrompt}
            currentInput={value}
          />
          <VoiceInput onTranscript={onTranscript} disabled={loading} />
          <button
            onClick={onSend}
            disabled={isDisabled}
            aria-label="Send message"
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
    </div>
  );
}

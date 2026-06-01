'use client';
import { useState, useRef, useEffect, useCallback, useMemo, type KeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';
import { AGENT_CFG, DEFAULT_AGENT_CFG, MODEL_COLORS } from '@/constants/agents';
import { useChat } from '@/hooks/useChat';
import { FileUpload } from '@/components/FileUpload/FileUpload';
import { VoiceInput } from '@/components/VoiceInput/VoiceInput';
import { PromptLibrary } from '@/components/PromptLibrary/PromptLibrary';
import { StreamingCursor } from '@/components/StreamingCursor/StreamingCursor';
import { API_URL } from '@/constants/api';

// Approximate token count (4 chars ≈ 1 token)
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// Copy-to-clipboard button for code blocks
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  }, [text]);
  return (
    <button
      onClick={handleCopy}
      title="Copy code"
      className={`absolute top-2 right-2 text-[10px] px-2 py-0.5 rounded border transition-all cursor-pointer
        ${copied
          ? 'bg-green-900 border-green-700 text-green-300'
          : 'bg-surface-active border-border-strong text-text-faint hover:text-text-secondary'
        }`}
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  );
}

interface ChatViewProps {
  sessionId: string | null;
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  historyLoading?: boolean;
  onClearChat?: () => void;
}

// #26 — Quick-start chips for empty state
const QUICK_PROMPTS = [
  'Explain this codebase structure',
  'Write a Python async function',
  'How does vector search work?',
  'Debug this error: ',
  'Summarise recent changes',
  'Generate unit tests for: ',
];

// #23 — format timestamp
function formatTs(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000);
  if (diffMin < 1)  return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// #22 — Markdown renderer with syntax highlighting + copy button
function makeMdComponents(dark: boolean): Components {
  return {
  code({ className, children, ...props }) {
    const match   = /language-(\w+)/.exec(className || '');
    const isBlock = String(children).includes('\n');
    const codeText = String(children).replace(/\n$/, '');
    if (isBlock && match) {
      return (
        <div className="relative group">
          <CopyButton text={codeText} />
          <SyntaxHighlighter
            style={(dark ? vscDarkPlus : oneLight) as never}
            language={match[1]}
            PreTag="div"
            customStyle={{ margin: '8px 0', borderRadius: 8, fontSize: 12, border: '1px solid #334155', paddingTop: 28 }}
          >
            {codeText}
          </SyntaxHighlighter>
        </div>
      );
    }
    if (isBlock) {
      return (
        <div className="relative group">
          <CopyButton text={codeText} />
          <pre className="bg-surface-code border border-border-strong rounded-lg p-3 overflow-x-auto my-2 text-xs font-mono leading-relaxed pt-7">
            <code className={className} {...props}>{children}</code>
          </pre>
        </div>
      );
    }
    return (
      <code className="bg-surface-code border border-border-strong rounded px-1 py-0.5 text-[0.9em] font-mono" {...props}>
        {children}
      </code>
    );
  },
  p({ children })         { return <p className="my-1.5 leading-relaxed">{children}</p>; },
  ul({ children })        { return <ul className="my-1.5 pl-5">{children}</ul>; },
  ol({ children })        { return <ol className="my-1.5 pl-5">{children}</ol>; },
  li({ children })        { return <li className="mb-1">{children}</li>; },
  blockquote({ children }){ return <blockquote className="border-l-[3px] border-border-strong ml-0 pl-3 my-2 text-text-secondary">{children}</blockquote>; },
  h1({ children })        { return <h1 className="text-lg mt-3 mb-1.5 text-text-primary">{children}</h1>; },
  h2({ children })        { return <h2 className="text-base mt-2.5 mb-1 text-text-primary">{children}</h2>; },
  h3({ children })        { return <h3 className="text-sm mt-2 mb-1 text-text-primary">{children}</h3>; },
  };
}


export function ChatView({ sessionId, messages, setMessages, historyLoading, onClearChat }: ChatViewProps) {
  const [input, setInput]       = useState('');
  const [chatSearch, setChatSearch] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [syntaxDark, setSyntaxDark] = useState(true);
  const [focusedMsgIdx, setFocusedMsgIdx] = useState<number | null>(null);
  const [clipboardOffer, setClipboardOffer] = useState<string | null>(null);
  const bottomRef               = useRef<HTMLDivElement>(null);
  const searchRef               = useRef<HTMLInputElement>(null);
  const prevStreamRef           = useRef<string>('');
  const msgRefs                 = useRef<(HTMLDivElement | null)[]>([]);
  const { loading, send, streamingContent } = useChat(sessionId);

  // Filter messages by search query
  const filteredMessages = useMemo(() => {
    if (!chatSearch.trim()) return messages;
    const q = chatSearch.toLowerCase();
    return messages.filter(m => m.content.toLowerCase().includes(q));
  }, [messages, chatSearch]);

  // Toggle in-chat search with Ctrl+F
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        setShowSearch(s => !s);
        setTimeout(() => searchRef.current?.focus(), 50);
      }
      if (e.key === 'Escape') setShowSearch(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const handleExport = useCallback(async (format: 'json' | 'md') => {
    if (!sessionId) return;
    const resp = await fetch(`${API_URL}/history/${sessionId}/export?format=${format}`);
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = `${sessionId}.${format}`; a.click();
    URL.revokeObjectURL(url);
  }, [sessionId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // Keyboard navigation through messages (up/down when not typing)
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'TEXTAREA' || tag === 'INPUT') return;
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        const len = filteredMessages.length;
        if (len === 0) return;
        setFocusedMsgIdx((prev) => {
          let next = prev === null ? (e.key === 'ArrowUp' ? len - 1 : 0) : prev + (e.key === 'ArrowUp' ? -1 : 1);
          next = Math.max(0, Math.min(len - 1, next));
          msgRefs.current[next]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          return next;
        });
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [filteredMessages.length]);

  const handleSend = useCallback(async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    const ts = new Date().toISOString();
    // Optimistic: add user message immediately
    setMessages((prev) => [...prev, { role: 'user', content: msg, ts }]);
    setInput('');
    try {
      const response = await send(msg);
      setMessages((prev) => [...prev, { ...response, ts: new Date().toISOString() }]);
    } catch {
      // Rollback optimistic user message on error
      setMessages((prev) => prev.filter((m) => !(m.role === 'user' && m.content === msg && m.ts === ts)));
      setMessages((prev) => [...prev, { role: 'error', content: 'Failed to send message. Please try again.', ts: new Date().toISOString() }]);
    }
  }, [input, loading, send, setMessages]);

  // FE22 — Auto-scroll to bottom when streaming completes
  useEffect(() => {
    if (prevStreamRef.current && !streamingContent) {
      // Stream just ended
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevStreamRef.current = streamingContent;
  }, [streamingContent]);

  // FE7 — Clipboard-aware context injection: detect clipboard on textarea focus
  const handleTextareaFocus = useCallback(async () => {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip && clip.length > 10 && clip.length < 5000 && !input.includes(clip)) {
        // Only offer if clipboard looks like code or text (not a single word)
        if (clip.includes('\n') || clip.length > 80) {
          setClipboardOffer(clip);
        }
      }
    } catch {
      // Clipboard read denied — ignore silently
    }
  }, [input]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
    // FE18 — Ctrl+Enter also submits
    if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); handleSend(); }
  };

  const handleFileUploaded = (reference: string) => {
    setInput((prev) => prev ? `${prev} ${reference}` : reference);
  };

  const handleTranscript  = useCallback((text: string) => { setInput(text); }, []);
  const handleSelectPrompt = useCallback((content: string) => { setInput(content); }, []);

  const isEmpty = messages.length === 0;

  return (
    <div className="flex-1 flex flex-col overflow-hidden" role="tabpanel" id="panel-chat" aria-labelledby="tab-chat">
      {/* In-chat search bar */}
      {showSearch && (
        <div className="px-4 py-1.5 border-b border-border-dim bg-surface-base flex items-center gap-2 flex-shrink-0">
          <span className="text-text-faint text-xs">🔍</span>
          <input
            ref={searchRef}
            value={chatSearch}
            onChange={e => setChatSearch(e.target.value)}
            placeholder="Search messages… (Esc to close)"
            className="flex-1 bg-transparent text-text-primary text-xs outline-none"
          />
          {chatSearch && (
            <span className="text-text-ghost text-[10px]">
              {filteredMessages.length}/{messages.length}
            </span>
          )}
          <button onClick={() => { setChatSearch(''); setShowSearch(false); }}
            className="text-text-ghost hover:text-text-faint transition-colors text-sm">×</button>
        </div>
      )}

      {/* Toolbar */}
      {(messages.length > 0 || onClearChat) && (
        <div className="flex justify-end gap-1.5 px-4 py-1.5 border-b border-border-dim flex-shrink-0">
          {messages.length > 0 && (
            <>
              <button onClick={() => { setShowSearch(s => !s); setTimeout(() => searchRef.current?.focus(), 50); }}
                title="Search messages (Ctrl+F)"
                className="border border-border-strong rounded-md text-text-faint text-[11px] px-2.5 py-1 hover:text-text-secondary transition-colors">
                🔍
              </button>
              <button onClick={() => setSyntaxDark(d => !d)}
                title={syntaxDark ? 'Switch to light syntax theme' : 'Switch to dark syntax theme'}
                className="border border-border-strong rounded-md text-text-faint text-[11px] px-2.5 py-1 hover:text-text-secondary transition-colors">
                {syntaxDark ? '☀' : '🌙'}
              </button>
              <button onClick={() => handleExport('md')}
                className="border border-border-strong rounded-md text-text-faint text-[11px] px-2.5 py-1 hover:text-text-secondary transition-colors">
                Export .md
              </button>
              <button onClick={() => handleExport('json')}
                className="border border-border-strong rounded-md text-text-faint text-[11px] px-2.5 py-1 hover:text-text-secondary transition-colors">
                Export .json
              </button>
            </>
          )}
          {messages.length > 0 && onClearChat && (
            <button onClick={onClearChat}
              className="border border-border-strong rounded-md text-text-faint text-[11px] px-2.5 py-1 hover:text-text-secondary transition-colors">
              Clear chat
            </button>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {/* Loading skeleton */}
        {historyLoading && (
          <div className="flex flex-col gap-2.5 py-5">
            {[80, 55, 95, 65].map((w, i) => (
              <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
                <div className="h-10 rounded-2xl animate-shimmer bg-gradient-to-r from-surface-card via-surface-active to-surface-card bg-[length:200%_100%]"
                  style={{ width: `${w}%` }} />
              </div>
            ))}
          </div>
        )}

        {/* #26 — Empty state with quick-start chips */}
        {!historyLoading && isEmpty && (
          <div className="flex flex-col items-center justify-center flex-1 gap-6 py-16">
            <div className="text-center">
              <div className="text-5xl mb-3">🧠</div>
              <p className="text-text-faint text-sm">How can I help you today?</p>
            </div>
            <div className="flex flex-wrap justify-center gap-2 max-w-lg">
              {QUICK_PROMPTS.map((prompt) => (
                <button key={prompt} onClick={() => handleSend(prompt)}
                  className="bg-surface-card border border-border-strong rounded-xl px-3 py-2 text-xs text-text-secondary hover:text-text-primary hover:border-accent-blue transition-all animate-fade-in">
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages */}
        {!historyLoading && filteredMessages.map((msg, i) => (
          <div key={`${msg.role}-${i}-${msg.content.slice(0, 20)}`}
            ref={el => { msgRefs.current[i] = el; }}
            className={focusedMsgIdx === i ? 'ring-1 ring-accent-blue/40 rounded-2xl' : ''}>
            <MessageBubble
              message={msg}
              messageIdx={i}
              sessionId={sessionId}
              searchQuery={chatSearch}
              syntaxDark={syntaxDark}
              onRetry={msg.role === 'assistant' ? async () => {
                const userMsg = messages.slice(0, i).reverse().find(m => m.role === 'user');
                if (!userMsg || loading) return;
                const response = await send(userMsg.content);
                setMessages((prev) => [...prev, { ...response, ts: new Date().toISOString() }]);
              } : undefined}
            />
          </div>
        ))}

        {/* Thinking / streaming */}
        {loading && !streamingContent && <ThinkingIndicator />}
        {loading && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[75%] bg-surface-card rounded-2xl rounded-bl-sm px-3.5 py-2.5 text-sm text-text-primary leading-relaxed">
              <span className="whitespace-pre-wrap font-[inherit]">{streamingContent}</span>
              <StreamingCursor />
              <div className="text-[10px] text-text-ghost mt-1">
                ~{estimateTokens(streamingContent)} tokens
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* FE7 — Clipboard offer banner */}
      {clipboardOffer && (
        <div className="px-4 py-2 border-t border-border-dim bg-surface-panel flex items-center gap-3 text-xs flex-shrink-0">
          <span className="text-text-faint flex-1 truncate">
            Clipboard: <span className="text-text-secondary">{clipboardOffer.slice(0, 80)}{clipboardOffer.length > 80 ? '…' : ''}</span>
          </span>
          <button
            onClick={() => { setInput(prev => prev ? `${prev}\n\n${clipboardOffer}` : clipboardOffer); setClipboardOffer(null); }}
            className="border border-accent-blue text-accent-blue-light rounded px-2 py-0.5 hover:bg-blue-900/30 transition-colors"
          >
            Inject
          </button>
          <button
            onClick={() => setClipboardOffer(null)}
            className="text-text-ghost hover:text-text-faint transition-colors px-1"
            title="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      <ChatInput
        value={input}
        loading={loading}
        sessionId={sessionId}
        onChange={setInput}
        onKeyDown={handleKeyDown}
        onFocus={handleTextareaFocus}
        onSend={() => handleSend()}
        onFileUploaded={handleFileUploaded}
        onTranscript={handleTranscript}
        onSelectPrompt={handleSelectPrompt}
      />
    </div>
  );
}

// ── MessageBubble ─────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: ChatMessage;
  messageIdx: number;
  sessionId: string | null;
  searchQuery?: string;
  syntaxDark?: boolean;
  onRetry?: () => void;
}

function MessageBubble({ message: msg, messageIdx, sessionId, searchQuery, syntaxDark = true, onRetry }: MessageBubbleProps) {
  const mdComps = useMemo(() => makeMdComponents(syntaxDark), [syntaxDark]);
  const agentCfg = (name?: string) => name ? (AGENT_CFG[name] ?? DEFAULT_AGENT_CFG) : DEFAULT_AGENT_CFG;
  const isUser   = msg.role === 'user';
  const isError  = msg.role === 'error';
  const [rating, setRating] = useState<1 | -1 | null>(null);

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
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div className="max-w-[75%]">
        {/* #29 — agent/model badge row as pills */}
        {msg.role === 'assistant' && (msg.model || msg.agent) && (
          <div className="flex items-center gap-1.5 mb-1 flex-wrap">
            {msg.model && (
              <span className="inline-flex items-center gap-1 text-[11px] border border-border-strong rounded-full px-2 py-0.5"
                style={{ color: MODEL_COLORS[msg.model] ?? '#94a3b8', borderColor: `${MODEL_COLORS[msg.model] ?? '#334155'}40` }}>
                ◆ {msg.model}
              </span>
            )}
            {msg.agent && (
              <span className="inline-flex items-center gap-1 text-[11px] border border-border-dim rounded-full px-2 py-0.5 text-text-faint">
                {agentCfg(msg.agent).icon} {msg.agent}
              </span>
            )}
            {msg.tools && msg.tools.length > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] border border-yellow-900 rounded-full px-2 py-0.5 text-accent-yellow">
                🔧 {msg.tools.join(', ')}
              </span>
            )}
          </div>
        )}

        <div className={`rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed
          ${isUser  ? 'bg-accent-blue text-white rounded-br-sm'
          : isError ? 'bg-red-950 text-red-300 rounded-bl-sm border border-red-900'
          :           'bg-surface-card text-text-primary rounded-bl-sm'}`}>
          {isUser || isError ? (
            <pre className="m-0 whitespace-pre-wrap font-[inherit]">{msg.content}</pre>
          ) : (
            <div className="font-[inherit]">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComps}>
                {msg.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* #23 — timestamp */}
        {msg.ts && (
          <div className={`text-[10px] text-text-ghost mt-0.5 ${isUser ? 'text-right' : 'text-left'}`}>
            {formatTs(msg.ts)}
          </div>
        )}

        {/* Actions for assistant messages */}
        {msg.role === 'assistant' && (
          <div className="flex items-center gap-1.5 mt-1">
            <button onClick={() => handleFeedback(1)} title="Helpful"
              className={`text-sm p-0.5 transition-opacity border-none bg-transparent cursor-pointer ${rating === 1 ? 'opacity-100' : 'opacity-30 hover:opacity-70'}`}>👍</button>
            <button onClick={() => handleFeedback(-1)} title="Not helpful"
              className={`text-sm p-0.5 transition-opacity border-none bg-transparent cursor-pointer ${rating === -1 ? 'opacity-100' : 'opacity-30 hover:opacity-70'}`}>👎</button>
            <TtsButton text={msg.content} />
            {onRetry && (
              <button onClick={onRetry}
                className="border border-border-strong rounded px-1.5 py-0.5 text-[10px] text-text-muted hover:text-text-secondary transition-colors ml-1">
                ↺ retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── TTS Button ────────────────────────────────────────────────────────────────
function TtsButton({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);
  const toggle = useCallback(() => {
    if (!window.speechSynthesis) return;
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return; }
    const clean = text.replace(/[#*`_\[\]<>]/g, '').slice(0, 3000);
    const utt   = new SpeechSynthesisUtterance(clean);
    utt.onend = utt.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utt);
    setSpeaking(true);
  }, [text, speaking]);
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
  return (
    <button onClick={toggle} title={speaking ? 'Stop reading' : 'Read aloud'}
      className={`text-sm p-0.5 border-none bg-transparent cursor-pointer transition-opacity ${speaking ? 'opacity-80' : 'opacity-30 hover:opacity-60'}`}>
      {speaking ? '⏹' : '🔊'}
    </button>
  );
}

// ── ThinkingIndicator ─────────────────────────────────────────────────────────
function ThinkingIndicator() {
  return (
    <div className="flex">
      <div className="bg-surface-card rounded-2xl rounded-bl-sm px-3.5 py-2.5">
        <div className="flex gap-1">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-[7px] h-[7px] rounded-full bg-text-faint animate-dot-bounce"
              style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── ChatInput ─────────────────────────────────────────────────────────────────
interface ChatInputProps {
  value: string; loading: boolean; sessionId: string | null;
  onChange: (v: string) => void; onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onFocus?: () => void;
  onSend: () => void; onFileUploaded: (ref: string, name: string) => void;
  onTranscript: (t: string) => void; onSelectPrompt: (c: string) => void;
}

const _CHAR_WARN = 2000;
const _CHAR_MAX  = 4000;

function ChatInput({ value, loading, sessionId, onChange, onKeyDown, onFocus, onSend, onFileUploaded, onTranscript, onSelectPrompt }: ChatInputProps) {
  const isDisabled  = loading || !value.trim();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const charCount   = value.length;
  const tokenEst    = estimateTokens(value);
  const counterColor = charCount >= _CHAR_MAX ? 'text-red-400' : charCount >= _CHAR_WARN ? 'text-accent-yellow' : 'text-text-ghost';

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 300)}px`;
  }, [value]);

  return (
    <div className="px-4 py-3 bg-surface-base border-t border-border-dim flex-shrink-0">
      {/* Character / token counter */}
      {value.length > 0 && (
        <div className={`text-right text-[10px] mb-1 max-w-[800px] mx-auto ${counterColor}`}>
          {charCount} chars · ~{tokenEst} tokens · Ctrl+Enter to send
        </div>
      )}
      <div className="flex gap-2 max-w-[800px] mx-auto items-end">
        <div className="flex items-center gap-0.5 pb-0.5">
          <FileUpload sessionId={sessionId} onUploaded={onFileUploaded} />
        </div>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={onFocus}
          placeholder="Ask a question… (Enter to send, Ctrl+Enter, Shift+Enter for new line)"
          rows={1}
          className="flex-1 bg-surface-input text-text-primary border border-border-strong rounded-xl px-3.5 py-2.5 text-sm resize-none outline-none font-[inherit] leading-relaxed overflow-y-auto min-h-[42px] max-h-[300px] focus:border-accent-blue transition-colors"
        />

        <div className="flex items-center gap-0.5 pb-0.5">
          <PromptLibrary sessionId={sessionId} onSelectPrompt={onSelectPrompt} currentInput={value} />
          <VoiceInput onTranscript={onTranscript} disabled={loading} />
          <button
            onClick={onSend}
            disabled={isDisabled}
            aria-label="Send message"
            className={`rounded-xl px-4 py-2.5 text-base text-text-primary transition-colors ${
              isDisabled ? 'bg-surface-active cursor-not-allowed' : 'bg-accent-blue hover:bg-blue-500 cursor-pointer'
            }`}
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}

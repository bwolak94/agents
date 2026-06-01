'use client';
import { useState, useEffect } from 'react';
import { API_URL } from '@/constants/api';
import { useChat } from '@/hooks/useChat';

interface Message {
  role: string;
  content: string;
  ts?: string;
}

interface PaneProps {
  sessionId: string;
  onChangeSession: (id: string) => void;
  allSessions: string[];
}

function ChatPane({ sessionId, onChangeSession, allSessions }: PaneProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const { loading, send } = useChat(sessionId);

  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_URL}/history/${sessionId}`)
      .then(r => r.json())
      .then(d => setMessages(d.messages ?? []))
      .catch(() => {});
  }, [sessionId]);

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setMessages(prev => [...prev, { role: 'user', content: msg, ts: new Date().toISOString() }]);
    setInput('');
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const resp = await send(msg) as any;
      setMessages(prev => [...prev, { role: 'assistant', content: resp?.response ?? resp ?? '', ts: new Date().toISOString() }]);
    } catch {
      setMessages(prev => [...prev, { role: 'error', content: 'Error sending message', ts: new Date().toISOString() }]);
    }
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid #1e293b', overflow: 'hidden' }}>
      {/* Session selector */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Session</span>
        <select
          value={sessionId}
          onChange={e => onChangeSession(e.target.value)}
          style={{
            flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
            color: '#e2e8f0', fontSize: 12, padding: '3px 8px', outline: 'none',
          }}
        >
          {allSessions.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
            background: m.role === 'user' ? '#1e3a5f' : '#1e293b',
            borderRadius: 10, padding: '8px 12px', maxWidth: '85%',
            fontSize: 13, color: '#e2e8f0', lineHeight: 1.5,
          }}>
            {m.content}
          </div>
        ))}
        {loading && (
          <div style={{ alignSelf: 'flex-start', color: '#475569', fontSize: 12 }}>Thinking…</div>
        )}
      </div>

      {/* Input */}
      <div style={{ padding: 8, borderTop: '1px solid #1e293b', display: 'flex', gap: 6 }}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
          placeholder="Message… (Enter to send)"
          style={{
            flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
            color: '#e2e8f0', fontSize: 13, padding: '8px 10px', outline: 'none',
            resize: 'none', height: 56, fontFamily: 'inherit',
          }}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          style={{
            background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff',
            fontSize: 12, padding: '0 14px', cursor: 'pointer', fontWeight: 600,
            opacity: loading || !input.trim() ? 0.5 : 1,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

export function SideBySideView() {
  const [allSessions, setAllSessions] = useState<string[]>([]);
  const [leftSession, setLeftSession] = useState('default');
  const [rightSession, setRightSession] = useState('default');

  useEffect(() => {
    fetch(`${API_URL}/sessions?limit=50`)
      .then(r => r.json())
      .then(d => {
        const ids = (d.sessions ?? []).map((s: { session_id: string }) => s.session_id);
        if (!ids.includes('default')) ids.unshift('default');
        setAllSessions(ids);
        if (ids.length > 1) setRightSession(ids[1]);
      })
      .catch(() => setAllSessions(['default']));
  }, []);

  return (
    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', height: '100%' }}>
      <ChatPane sessionId={leftSession} onChangeSession={setLeftSession} allSessions={allSessions} />
      <ChatPane sessionId={rightSession} onChangeSession={setRightSession} allSessions={allSessions} />
    </div>
  );
}

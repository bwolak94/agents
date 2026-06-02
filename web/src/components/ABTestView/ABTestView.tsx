'use client';
import { useState } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface ABResult {
  message: string;
  variant_a: { system_prompt: string; response: string; duration_ms: number };
  variant_b: { system_prompt: string; response: string; duration_ms: number };
}

export function ABTestView() {
  const [message, setMessage] = useState('');
  const [promptA, setPromptA] = useState('You are a concise assistant. Answer briefly.');
  const [promptB, setPromptB] = useState('You are a detailed assistant. Provide comprehensive answers.');
  const [model, setModel] = useState('claude');
  const [sessionId, setSessionId] = useState('ab-test');
  const [result, setResult] = useState<ABResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [winner, setWinner] = useState<'A' | 'B' | null>(null);

  const runTest = async () => {
    if (!message.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);
    setWinner(null);

    try {
      const res = await fetch(`${API_BASE}/chat/ab-test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          model,
          system_prompt_a: promptA,
          system_prompt_b: promptB,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto', color: '#e2e8f0' }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 20, color: '#94a3b8' }}>
        A/B System Prompt Testing
      </h2>

      {/* Config */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#64748b', marginBottom: 4 }}>Variant A — System Prompt</label>
          <textarea
            value={promptA}
            onChange={e => setPromptA(e.target.value)}
            rows={3}
            style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', padding: 10, fontSize: 13, resize: 'vertical', boxSizing: 'border-box' }}
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#64748b', marginBottom: 4 }}>Variant B — System Prompt</label>
          <textarea
            value={promptB}
            onChange={e => setPromptB(e.target.value)}
            rows={3}
            style={{ width: '100%', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', padding: 10, fontSize: 13, resize: 'vertical', boxSizing: 'border-box' }}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <input
          value={message}
          onChange={e => setMessage(e.target.value)}
          placeholder="Test message..."
          style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', padding: '8px 12px', fontSize: 14 }}
          onKeyDown={e => e.key === 'Enter' && runTest()}
        />
        <select
          value={model}
          onChange={e => setModel(e.target.value)}
          style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', padding: '8px 12px', fontSize: 13 }}
        >
          {['claude', 'gemini', 'ollama/llama3'].map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <button
          onClick={runTest}
          disabled={loading || !message.trim()}
          style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontSize: 14, opacity: loading ? 0.6 : 1 }}
        >
          {loading ? 'Running...' : 'Run A/B Test'}
        </button>
      </div>

      {error && <div style={{ color: '#f87171', fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {/* Results */}
      {result && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {(['A', 'B'] as const).map(v => {
              const variant = v === 'A' ? result.variant_a : result.variant_b;
              const isWinner = winner === v;
              return (
                <div
                  key={v}
                  style={{
                    background: isWinner ? 'rgba(34,197,94,0.08)' : '#1e293b',
                    border: `1px solid ${isWinner ? '#22c55e' : '#334155'}`,
                    borderRadius: 8, padding: 16,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontWeight: 700, color: isWinner ? '#22c55e' : '#94a3b8', fontSize: 14 }}>
                      Variant {v} {isWinner ? ' (Winner)' : ''}
                    </span>
                    <span style={{ fontSize: 11, color: '#475569' }}>{variant.duration_ms}ms</span>
                  </div>
                  <div style={{ color: '#64748b', fontSize: 11, marginBottom: 6 }}>
                    System: <em>{variant.system_prompt.slice(0, 60)}...</em>
                  </div>
                  <div style={{ color: '#e2e8f0', fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
                    {variant.response}
                  </div>
                  {!winner && (
                    <button
                      onClick={() => setWinner(v)}
                      style={{ marginTop: 12, background: '#1e3a5f', color: '#60a5fa', border: '1px solid #1d4ed8', borderRadius: 6, padding: '5px 14px', cursor: 'pointer', fontSize: 12 }}
                    >
                      This one is better
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {winner && (
            <div style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid #22c55e', borderRadius: 8, padding: '12px 16px', color: '#86efac', fontSize: 14 }}>
              Variant {winner} selected as winner. Use its system prompt in production.
            </div>
          )}
        </>
      )}
    </div>
  );
}

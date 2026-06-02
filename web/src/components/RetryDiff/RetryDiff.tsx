'use client';
import { useState, useCallback } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface RetryDiffProps {
  sessionId: string;
  messageIdx: number;
  originalResponse: string;
  userMessage: string;
  model?: string;
  onClose: () => void;
}

interface DiffLine {
  type: 'added' | 'removed' | 'equal';
  text: string;
}

function computeDiff(original: string, revised: string): DiffLine[] {
  const origLines = original.split('\n');
  const revLines = revised.split('\n');
  const result: DiffLine[] = [];

  // Simple LCS-based line diff
  const n = origLines.length;
  const m = revLines.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (origLines[i] === revLines[j]) {
        dp[i][j] = 1 + dp[i + 1][j + 1];
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && origLines[i] === revLines[j]) {
      result.push({ type: 'equal', text: origLines[i] });
      i++; j++;
    } else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) {
      result.push({ type: 'added', text: revLines[j] });
      j++;
    } else {
      result.push({ type: 'removed', text: origLines[i] });
      i++;
    }
  }
  return result;
}

export function RetryDiff({ sessionId, messageIdx, originalResponse, userMessage, model = 'claude', onClose }: RetryDiffProps) {
  const [revised, setRevised] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRevised = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage, session_id: sessionId, preferred_model: model }),
      });
      const data = await res.json();
      setRevised(data.response ?? '');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId, userMessage, model]);

  const diff = revised != null ? computeDiff(originalResponse, revised) : null;

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#0f172a', border: '1px solid #334155', borderRadius: 12,
        width: '90vw', maxWidth: 900, maxHeight: '80vh', display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: '#94a3b8', fontSize: 14, fontWeight: 600 }}>Retry Diff — message #{messageIdx}</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={fetchRevised}
              disabled={loading}
              style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13 }}
            >
              {loading ? 'Retrying...' : revised != null ? 'Retry again' : 'Retry with ' + model}
            </button>
            <button
              onClick={onClose}
              style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13 }}
            >
              Close
            </button>
          </div>
        </div>

        {/* Diff view */}
        <div style={{ overflowY: 'auto', flex: 1, padding: 16, fontFamily: 'monospace', fontSize: 12 }}>
          {error && <div style={{ color: '#f87171', marginBottom: 8 }}>Error: {error}</div>}

          {diff == null ? (
            <div style={{ color: '#475569', textAlign: 'center', paddingTop: 40 }}>
              Click &ldquo;Retry&rdquo; to generate a new response and see the diff
            </div>
          ) : (
            diff.map((line, idx) => (
              <div
                key={idx}
                style={{
                  padding: '1px 8px',
                  background: line.type === 'added' ? 'rgba(34,197,94,0.12)' : line.type === 'removed' ? 'rgba(239,68,68,0.12)' : 'transparent',
                  color: line.type === 'added' ? '#86efac' : line.type === 'removed' ? '#fca5a5' : '#94a3b8',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
                {line.text}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

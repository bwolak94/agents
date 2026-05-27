'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/constants/api';

const AGENT_TYPES = ['general_agent', 'code_agent', 'research_agent', 'learn_agent', 'file_agent', 'planner_agent'];

interface MemoryInspectorProps {
  sessionId: string | null;
}

export function MemoryInspector({ sessionId }: MemoryInspectorProps) {
  const [selectedAgent, setSelectedAgent] = useState(AGENT_TYPES[0]);
  const [memory, setMemory] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [editing, setEditing] = useState(false);

  const fetchMemory = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const resp = await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`);
      const data = await resp.json();
      const mem = data.memory || '';
      setMemory(mem);
      setEditContent(mem);
    } catch {
      setMemory('');
      setEditContent('');
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectedAgent]);

  useEffect(() => {
    fetchMemory();
  }, [fetchMemory]);

  const handleSave = async () => {
    if (!sessionId) return;
    setSaving(true);
    try {
      await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`, {
        method: 'DELETE',
      });
      if (editContent.trim()) {
        // Write new content via a chat-level memory write isn't exposed directly;
        // we delete and the agent will re-populate. For now just clear.
        // TODO: add PUT /memory/{session}/{agent} endpoint
      }
      setMemory(editContent);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!sessionId || !window.confirm(`Clear memory for ${selectedAgent}?`)) return;
    await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`, { method: 'DELETE' });
    setMemory('');
    setEditContent('');
    setEditing(false);
  };

  if (!sessionId) {
    return (
      <div style={{ padding: 24, color: '#475569', textAlign: 'center' }}>
        No active session
      </div>
    );
  }

  return (
    <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16, height: '100%', overflowY: 'auto' }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16, color: '#e2e8f0', fontWeight: 600 }}>Memory Inspector</h2>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
          Session: <span style={{ color: '#60a5fa' }}>{sessionId}</span>
        </p>
      </div>

      {/* Agent type selector */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {AGENT_TYPES.map((agent) => (
          <button
            key={agent}
            onClick={() => { setSelectedAgent(agent); setEditing(false); }}
            style={{
              background: selectedAgent === agent ? '#1d4ed8' : '#1e293b',
              border: '1px solid #334155',
              borderRadius: 6,
              color: selectedAgent === agent ? '#fff' : '#94a3b8',
              cursor: 'pointer',
              fontSize: 11,
              padding: '4px 10px',
              transition: 'all 0.15s',
            }}
          >
            {agent.replace('_agent', '')}
          </button>
        ))}
      </div>

      {/* Memory content */}
      <div style={{ flex: 1 }}>
        {loading ? (
          <div style={{ color: '#475569', fontSize: 13 }}>Loading...</div>
        ) : editing ? (
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            style={{
              width: '100%',
              minHeight: 200,
              background: '#0d1117',
              border: '1px solid #334155',
              borderRadius: 8,
              color: '#e2e8f0',
              fontSize: 12,
              padding: 12,
              fontFamily: 'monospace',
              resize: 'vertical',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        ) : (
          <pre
            style={{
              background: '#0d1117',
              border: '1px solid #1e293b',
              borderRadius: 8,
              color: memory ? '#e2e8f0' : '#475569',
              fontSize: 12,
              padding: 12,
              minHeight: 100,
              whiteSpace: 'pre-wrap',
              fontFamily: 'monospace',
              margin: 0,
            }}
          >
            {memory || `No memory stored for ${selectedAgent}`}
          </pre>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8 }}>
        {editing ? (
          <>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{ background: '#1d4ed8', border: 'none', borderRadius: 6, color: '#fff', cursor: 'pointer', fontSize: 12, padding: '6px 14px' }}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => { setEditing(false); setEditContent(memory); }}
              style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '6px 14px' }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setEditing(true)}
              style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '6px 14px' }}
            >
              Edit
            </button>
            <button
              onClick={handleClear}
              style={{ background: 'none', border: '1px solid #450a0a', borderRadius: 6, color: '#f87171', cursor: 'pointer', fontSize: 12, padding: '6px 14px' }}
            >
              Clear
            </button>
            <button
              onClick={fetchMemory}
              style={{ background: 'none', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '6px 14px' }}
            >
              Refresh
            </button>
          </>
        )}
      </div>
    </div>
  );
}

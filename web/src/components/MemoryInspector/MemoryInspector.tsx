'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/constants/api';
import { ConfirmModal } from '@/components/ConfirmModal/ConfirmModal';

const AGENT_TYPES = ['general_agent', 'code_agent', 'research_agent', 'learn_agent', 'file_agent', 'planner_agent'];

interface MemoryInspectorProps {
  sessionId: string | null;
}

export function MemoryInspector({ sessionId }: MemoryInspectorProps) {
  const [selectedAgent, setSelectedAgent] = useState(AGENT_TYPES[0]);
  const [memory, setMemory]               = useState('');
  const [loading, setLoading]             = useState(false);
  const [saving, setSaving]               = useState(false);
  const [editContent, setEditContent]     = useState('');
  const [editing, setEditing]             = useState(false);
  const [confirmClear, setConfirmClear]   = useState(false);  // #25

  const fetchMemory = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const resp = await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`);
      const data = await resp.json();
      const mem  = data.memory || '';
      setMemory(mem);
      setEditContent(mem);
    } catch {
      setMemory(''); setEditContent('');
    } finally {
      setLoading(false);
    }
  }, [sessionId, selectedAgent]);

  useEffect(() => { fetchMemory(); }, [fetchMemory]);

  const handleSave = async () => {
    if (!sessionId) return;
    setSaving(true);
    try {
      await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`, { method: 'DELETE' });
      setMemory(editContent);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!sessionId) return;
    await fetch(`${API_URL}/memory/${sessionId}/${selectedAgent}`, { method: 'DELETE' });
    setMemory(''); setEditContent(''); setEditing(false);
    setConfirmClear(false);
  };

  if (!sessionId) {
    return (
      <div className="p-6 text-text-faint text-center text-sm">No active session</div>
    );
  }

  return (
    <>
      {/* #25 — Themed confirm modal instead of window.confirm */}
      {confirmClear && (
        <ConfirmModal
          message={`Clear memory for ${selectedAgent}? This cannot be undone.`}
          confirmLabel="Clear memory"
          danger
          onConfirm={handleClear}
          onCancel={() => setConfirmClear(false)}
        />
      )}

      <div className="p-5 flex flex-col gap-4 h-full overflow-y-auto">
        <div>
          <h2 className="m-0 text-base font-semibold text-text-primary">Memory Inspector</h2>
          <p className="mt-1 mb-0 text-xs text-text-faint">
            Session: <span className="text-accent-blue-light">{sessionId}</span>
          </p>
        </div>

        {/* Agent selector */}
        <div className="flex gap-1.5 flex-wrap">
          {AGENT_TYPES.map((agent) => (
            <button key={agent} onClick={() => { setSelectedAgent(agent); setEditing(false); }}
              className={`border rounded-md text-[11px] px-2.5 py-1 transition-all ${
                selectedAgent === agent
                  ? 'bg-accent-blue border-accent-blue text-white'
                  : 'bg-surface-active border-border-strong text-text-secondary hover:text-text-primary'
              }`}>
              {agent.replace('_agent', '')}
            </button>
          ))}
        </div>

        {/* Memory content */}
        <div className="flex-1">
          {loading ? (
            <div className="text-text-faint text-sm">Loading...</div>
          ) : editing ? (
            <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)}
              className="w-full min-h-[200px] bg-surface-code border border-border-strong rounded-lg text-text-primary text-xs p-3 font-mono resize-y outline-none focus:border-accent-blue transition-colors box-border" />
          ) : (
            <pre className={`bg-surface-code border border-border-base rounded-lg text-xs p-3 min-h-[100px] whitespace-pre-wrap font-mono m-0 ${memory ? 'text-text-primary' : 'text-text-faint'}`}>
              {memory || `No memory stored for ${selectedAgent}`}
            </pre>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          {editing ? (
            <>
              <button onClick={handleSave} disabled={saving}
                className="bg-accent-blue border-none rounded-md text-white text-xs px-3.5 py-1.5 cursor-pointer hover:bg-blue-500 transition-colors disabled:opacity-50">
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => { setEditing(false); setEditContent(memory); }}
                className="bg-surface-active border border-border-strong rounded-md text-text-secondary text-xs px-3.5 py-1.5 cursor-pointer hover:text-text-primary transition-colors">
                Cancel
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)}
                className="bg-surface-active border border-border-strong rounded-md text-text-secondary text-xs px-3.5 py-1.5 cursor-pointer hover:text-text-primary transition-colors">
                Edit
              </button>
              <button onClick={() => setConfirmClear(true)}
                className="border border-red-900 rounded-md text-red-400 text-xs px-3.5 py-1.5 cursor-pointer hover:bg-red-950 transition-colors">
                Clear
              </button>
              <button onClick={fetchMemory}
                className="border border-border-strong rounded-md text-text-muted text-xs px-3.5 py-1.5 cursor-pointer hover:text-text-secondary transition-colors">
                Refresh
              </button>
            </>
          )}
        </div>
      </div>
    </>
  );
}

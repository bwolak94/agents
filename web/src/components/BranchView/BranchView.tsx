'use client';
import { useState, useCallback } from 'react';
import type { ChatMessage } from '@/types/chat';
import { API_URL } from '@/constants/api';

interface Props {
  messages: ChatMessage[];
  sessionId: string | null;
  onNewSession: (id: string) => void;
}

function generateBranchId(base: string): string {
  return `${base}-branch-${Date.now().toString(36)}`;
}

export function BranchView({ messages, sessionId, onNewSession }: Props) {
  const [branchAt, setBranchAt]     = useState<number | null>(null);
  const [branching, setBranching]   = useState(false);
  const [branchId, setBranchId]     = useState<string | null>(null);
  const [branchMsgs, setBranchMsgs] = useState<ChatMessage[]>([]);

  const handleFork = useCallback(async (msgIdx: number) => {
    if (!sessionId) return;
    const newId = generateBranchId(sessionId);
    setBranching(true);
    try {
      const res = await fetch(`${API_URL}/sessions/${sessionId}/fork`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_session_id: newId, at_message_index: msgIdx + 1 }),
      });
      if (!res.ok) throw new Error('Fork failed');
      setBranchAt(msgIdx);
      setBranchId(newId);
      setBranchMsgs(messages.slice(0, msgIdx + 1));
    } catch { /* ignore */ }
    setBranching(false);
  }, [sessionId, messages]);

  const handleOpenBranch = useCallback(() => {
    if (branchId) onNewSession(branchId);
  }, [branchId, onNewSession]);

  return (
    <div className="flex flex-col h-full">
      {/* Branch indicator */}
      {branchId && (
        <div className="px-4 py-2 bg-blue-950/50 border-b border-accent-blue/20 flex items-center justify-between flex-shrink-0">
          <div className="text-xs text-accent-blue">
            Branch created from message #{(branchAt ?? 0) + 1}
          </div>
          <button
            onClick={handleOpenBranch}
            className="text-xs bg-accent-blue text-white rounded-lg px-2.5 py-1 hover:bg-blue-500 transition-colors"
          >
            Open branch →
          </button>
        </div>
      )}

      {/* Message list with fork buttons */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
        {messages.map((msg, i) => (
          <div key={i} className="group relative flex items-start gap-2">
            <div className={`flex-1 rounded-xl px-3 py-2 text-sm
              ${msg.role === 'user'
                ? 'bg-accent-blue/10 border border-accent-blue/20 text-text-primary ml-8'
                : 'bg-surface-card border border-border-dim text-text-primary'
              }`}
            >
              <div className="text-[10px] text-text-ghost mb-1 font-semibold uppercase tracking-wider">
                {msg.role}
              </div>
              <p className="text-xs leading-relaxed whitespace-pre-wrap line-clamp-4">{msg.content}</p>
            </div>

            {/* Fork button — appears on hover */}
            <button
              onClick={() => handleFork(i)}
              disabled={branching}
              title={`Fork conversation at message #${i + 1}`}
              className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 mt-2 text-[10px] border border-border-strong rounded px-1.5 py-0.5 text-text-ghost hover:text-accent-blue hover:border-accent-blue transition-colors disabled:opacity-30"
            >
              ⑂
            </button>
          </div>
        ))}

        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-text-ghost text-xs">
            No messages yet. Start a conversation to enable branching.
          </div>
        )}
      </div>
    </div>
  );
}

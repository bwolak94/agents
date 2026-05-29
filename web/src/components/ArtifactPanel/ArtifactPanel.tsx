'use client';
import { useMemo, useState, useCallback } from 'react';
import type { ChatMessage } from '@/types/chat';

interface Artifact {
  id: string;
  type: 'code' | 'json' | 'text';
  language: string;
  content: string;
  msgIdx: number;
}

function extractArtifacts(messages: ChatMessage[]): Artifact[] {
  const artifacts: Artifact[] = [];
  messages.forEach((msg, msgIdx) => {
    if (msg.role !== 'assistant') return;
    // Code blocks
    const codeRe = /```(\w*)\n([\s\S]*?)```/g;
    let m: RegExpExecArray | null;
    while ((m = codeRe.exec(msg.content)) !== null) {
      const lang = m[1] || 'text';
      const content = m[2].trim();
      artifacts.push({
        id: `${msgIdx}-${artifacts.length}`,
        type: lang === 'json' ? 'json' : lang ? 'code' : 'text',
        language: lang,
        content,
        msgIdx,
      });
    }
  });
  return artifacts;
}

interface Props {
  messages: ChatMessage[];
  collapsed?: boolean;
  onToggle?: () => void;
}

export function ArtifactPanel({ messages, collapsed = false, onToggle }: Props) {
  const [copied, setCopied] = useState<string | null>(null);
  const artifacts = useMemo(() => extractArtifacts(messages), [messages]);

  const handleCopy = useCallback(async (id: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(id);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* ignore */ }
  }, []);

  const handleDownload = useCallback((artifact: Artifact) => {
    const ext = artifact.language === 'python' ? 'py'
      : artifact.language === 'javascript' ? 'js'
      : artifact.language === 'typescript' ? 'ts'
      : artifact.language === 'json' ? 'json'
      : artifact.language || 'txt';
    const blob = new Blob([artifact.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `artifact-${artifact.id}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  if (collapsed) {
    return (
      <div className="w-8 flex-shrink-0 border-l border-border-dim bg-surface-panel flex flex-col items-center pt-3 gap-2">
        {artifacts.length > 0 && (
          <span className="text-[10px] font-bold text-accent-blue bg-blue-950 rounded-full px-1.5 py-0.5">
            {artifacts.length}
          </span>
        )}
        <button onClick={onToggle} title="Expand artifacts" className="text-text-ghost hover:text-text-muted transition-colors text-lg">‹</button>
      </div>
    );
  }

  return (
    <div className="w-[260px] flex-shrink-0 border-l border-border-dim bg-surface-panel flex flex-col overflow-hidden">
      <div className="px-3 py-2.5 border-b border-border-dim flex items-center justify-between flex-shrink-0">
        <span className="text-[11px] font-semibold text-text-muted uppercase tracking-widest">
          Artifacts
        </span>
        <div className="flex items-center gap-2">
          {artifacts.length > 0 && (
            <span className="text-[11px] font-bold text-accent-blue bg-blue-950/50 px-2 py-0.5 rounded-full">
              {artifacts.length}
            </span>
          )}
          {onToggle && (
            <button onClick={onToggle} title="Collapse artifacts"
              className="text-text-ghost hover:text-text-muted transition-colors text-base leading-none">›</button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {artifacts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-border-strong">
            <span className="text-2xl">📎</span>
            <span className="text-xs text-center">Code blocks and JSON objects from the chat appear here.</span>
          </div>
        ) : (
          artifacts.map((a) => (
            <div key={a.id} className="bg-surface-card border border-border-dim rounded-lg overflow-hidden">
              <div className="flex items-center justify-between px-2 py-1 bg-surface-active border-b border-border-dim">
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] font-mono text-accent-blue bg-blue-950/50 rounded px-1 py-0.5">
                    {a.language || 'text'}
                  </span>
                  <span className="text-[10px] text-text-ghost">msg #{a.msgIdx + 1}</span>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => handleCopy(a.id, a.content)}
                    title="Copy"
                    className="text-[10px] text-text-faint hover:text-text-secondary transition-colors px-1"
                  >
                    {copied === a.id ? '✓' : 'Copy'}
                  </button>
                  <button
                    onClick={() => handleDownload(a)}
                    title="Download"
                    className="text-[10px] text-text-faint hover:text-text-secondary transition-colors px-1"
                  >
                    ↓
                  </button>
                </div>
              </div>
              <pre className="p-2 text-[10px] font-mono text-text-secondary overflow-x-auto max-h-[120px] leading-relaxed">
                {a.content.slice(0, 500)}{a.content.length > 500 ? '…' : ''}
              </pre>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

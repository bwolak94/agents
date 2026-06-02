'use client';
import { useState, useEffect } from 'react';

const SHORTCUTS = [
  { keys: ['Enter'],          desc: 'Send message' },
  { keys: ['Shift', 'Enter'], desc: 'New line in message' },
  { keys: ['Ctrl', 'F'],      desc: 'Search in chat messages' },
  { keys: ['Ctrl', 'K'],      desc: 'Open command palette' },
  { keys: ['Ctrl', '?'],      desc: 'Show keyboard shortcuts' },
  { keys: ['Esc'],            desc: 'Close modal / search' },
  { keys: ['←', '→'],         desc: 'Navigate views (in header)' },
];

interface KeyboardShortcutsProps {
  open: boolean;
  onClose: () => void;
}

export function KeyboardShortcuts({ open, onClose }: KeyboardShortcutsProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[900] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-surface-card border border-border-strong rounded-2xl shadow-2xl p-6 w-80 max-w-[90vw]"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-text-primary font-semibold text-sm">Keyboard Shortcuts</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-text-ghost hover:text-text-faint transition-colors text-lg cursor-pointer border-none bg-transparent"
          >
            ×
          </button>
        </div>
        <div className="flex flex-col gap-2.5">
          {SHORTCUTS.map(({ keys, desc }) => (
            <div key={desc} className="flex items-center justify-between gap-3">
              <span className="text-text-secondary text-xs">{desc}</span>
              <div className="flex gap-1 flex-shrink-0">
                {keys.map((k, i) => (
                  <span key={i}>
                    <kbd className="bg-surface-active border border-border-strong rounded px-1.5 py-0.5 text-[10px] font-mono text-text-primary">
                      {k}
                    </kbd>
                    {i < keys.length - 1 && (
                      <span className="text-text-ghost text-[10px] mx-0.5">+</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

'use client';
import { useState } from 'react';
import { usePrompts } from '@/hooks/usePrompts';

interface PromptLibraryProps {
  sessionId: string | null;
  onSelectPrompt: (content: string) => void;
  currentInput?: string;
}

export function PromptLibrary({ sessionId, onSelectPrompt, currentInput = '' }: PromptLibraryProps) {
  const [open, setOpen] = useState(false);
  const [saveFormOpen, setSaveFormOpen] = useState(false);
  const [saveTitle, setSaveTitle] = useState('');
  const [saveTags, setSaveTags] = useState('');
  const [saving, setSaving] = useState(false);

  const { prompts, loading, savePrompt, deletePrompt } = usePrompts(sessionId);

  const handleSave = async () => {
    if (!saveTitle.trim() || !currentInput.trim()) return;
    setSaving(true);
    const tags = saveTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    await savePrompt(saveTitle.trim(), currentInput.trim(), tags);
    setSaveTitle('');
    setSaveTags('');
    setSaveFormOpen(false);
    setSaving(false);
  };

  const inputStyle: React.CSSProperties = {
    background: '#0d0d1a',
    color: '#e2e8f0',
    border: '1px solid #334155',
    borderRadius: 6,
    padding: '6px 10px',
    fontSize: 12,
    width: '100%',
    boxSizing: 'border-box',
    outline: 'none',
    fontFamily: 'inherit',
  };

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={() => setOpen((v) => !v)}
        title="Prompt Library"
        style={{
          background: open ? '#1a1a2e' : 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 8px',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 16,
          color: open ? '#e2e8f0' : '#64748b',
          transition: 'color 0.2s, background 0.2s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = open ? '#e2e8f0' : '#64748b';
        }}
      >
        📚
      </button>

      {/* Slide-in panel */}
      {open && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            right: 0,
            bottom: 0,
            width: 280,
            background: '#050509',
            borderLeft: '1px solid #1a1a2e',
            zIndex: 200,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Panel header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '12px 16px',
              borderBottom: '1px solid #1a1a2e',
              flexShrink: 0,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 13, color: '#e2e8f0' }}>
              📚 Prompt Library
            </span>
            <button
              onClick={() => setOpen(false)}
              style={{
                background: 'none',
                border: 'none',
                color: '#64748b',
                cursor: 'pointer',
                fontSize: 16,
                padding: 2,
              }}
            >
              ✕
            </button>
          </div>

          {/* Save current input */}
          {currentInput.trim() && (
            <div style={{ padding: '10px 16px', borderBottom: '1px solid #1a1a2e', flexShrink: 0 }}>
              {!saveFormOpen ? (
                <button
                  onClick={() => setSaveFormOpen(true)}
                  style={{
                    width: '100%',
                    background: '#1a1a2e',
                    color: '#94a3b8',
                    border: '1px solid #334155',
                    borderRadius: 8,
                    padding: '7px 12px',
                    cursor: 'pointer',
                    fontSize: 12,
                    textAlign: 'left',
                  }}
                >
                  💾 Save current input as prompt
                </button>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <input
                    value={saveTitle}
                    onChange={(e) => setSaveTitle(e.target.value)}
                    placeholder="Title"
                    style={inputStyle}
                  />
                  <input
                    value={saveTags}
                    onChange={(e) => setSaveTags(e.target.value)}
                    placeholder="Tags (comma separated)"
                    style={inputStyle}
                  />
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      onClick={handleSave}
                      disabled={saving || !saveTitle.trim()}
                      style={{
                        flex: 1,
                        background: saving || !saveTitle.trim() ? '#1a1a2e' : '#2563eb',
                        color: '#e2e8f0',
                        border: 'none',
                        borderRadius: 6,
                        padding: '6px',
                        cursor: saving || !saveTitle.trim() ? 'not-allowed' : 'pointer',
                        fontSize: 12,
                      }}
                    >
                      {saving ? 'Saving…' : 'Save'}
                    </button>
                    <button
                      onClick={() => {
                        setSaveFormOpen(false);
                        setSaveTitle('');
                        setSaveTags('');
                      }}
                      style={{
                        background: '#1a1a2e',
                        color: '#94a3b8',
                        border: 'none',
                        borderRadius: 6,
                        padding: '6px 10px',
                        cursor: 'pointer',
                        fontSize: 12,
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Prompt list */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
            {loading && (
              <div style={{ fontSize: 12, color: '#475569', textAlign: 'center', padding: 20 }}>
                Loading…
              </div>
            )}
            {!loading && prompts.length === 0 && (
              <div style={{ fontSize: 12, color: '#475569', textAlign: 'center', padding: 20 }}>
                No saved prompts yet.
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {prompts.map((prompt) => (
                <div
                  key={prompt.prompt_id}
                  style={{
                    background: '#0d0d1a',
                    border: '1px solid #1a1a2e',
                    borderRadius: 8,
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 12, color: '#e2e8f0' }}>
                    {prompt.title}
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', lineHeight: 1.4 }}>
                    {prompt.content.slice(0, 80)}
                    {prompt.content.length > 80 ? '…' : ''}
                  </div>
                  {prompt.tags.length > 0 && (
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {prompt.tags.map((tag) => (
                        <span
                          key={tag}
                          style={{
                            background: '#1a1a2e',
                            color: '#60a5fa',
                            fontSize: 10,
                            padding: '2px 6px',
                            borderRadius: 4,
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      onClick={() => {
                        onSelectPrompt(prompt.content);
                        setOpen(false);
                      }}
                      style={{
                        flex: 1,
                        background: '#1d4ed8',
                        color: '#e2e8f0',
                        border: 'none',
                        borderRadius: 6,
                        padding: '5px 8px',
                        cursor: 'pointer',
                        fontSize: 11,
                      }}
                    >
                      Use prompt
                    </button>
                    <button
                      onClick={() => deletePrompt(prompt.prompt_id)}
                      style={{
                        background: '#450a0a',
                        color: '#fca5a5',
                        border: 'none',
                        borderRadius: 6,
                        padding: '5px 8px',
                        cursor: 'pointer',
                        fontSize: 11,
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Backdrop */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 199,
            background: 'rgba(0,0,0,0.3)',
          }}
        />
      )}
    </>
  );
}

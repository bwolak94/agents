'use client';
import { useRef, useState, useCallback } from 'react';
import { API_URL } from '@/constants/api';

interface FileUploadProps {
  sessionId: string | null;
  onUploaded: (reference: string, filename: string) => void;
}

const MAX_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB

export function FileUpload({ sessionId, onUploaded }: FileUploadProps) {
  const inputRef    = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast]         = useState<string | null>(null);
  const [dragging, setDragging]   = useState(false);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const uploadFile = useCallback(async (file: File) => {
    if (file.size > MAX_SIZE_BYTES) {
      showToast('File too large. Maximum size is 10 MB.');
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const url = sessionId
        ? `${API_URL}/upload?session_id=${sessionId}`
        : `${API_URL}/upload`;
      const res = await fetch(url, { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
      const data = (await res.json()) as { reference: string };
      await navigator.clipboard.writeText(data.reference).catch(() => {});
      showToast(`Copied! Use in chat: ${data.reference}`);
      onUploaded(data.reference, file.name);
    } catch {
      showToast('Upload failed. Please try again.');
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }, [sessionId, onUploaded]);

  const handleClick = () => { if (!uploading) inputRef.current?.click(); };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
  };

  // Drag-and-drop handlers
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file && !uploading) uploadFile(file);
  };

  return (
    <div className="relative inline-flex items-center">
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.csv,.yaml,.yml,.pdf,.html,.css"
        className="hidden"
        onChange={handleFileChange}
      />
      <button
        onClick={handleClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        title={dragging ? 'Drop to upload' : 'Attach file (or drag & drop)'}
        aria-label="Attach file"
        disabled={uploading}
        className={`flex items-center justify-center rounded-lg p-1.5 text-base transition-all border
          ${dragging
            ? 'border-accent-blue bg-surface-active text-accent-blue-light scale-105'
            : uploading
              ? 'border-transparent text-border-strong cursor-not-allowed'
              : 'border-transparent text-text-faint hover:text-text-secondary hover:border-border-strong cursor-pointer'
          }`}
      >
        {uploading ? (
          <span className="inline-block w-3.5 h-3.5 border-2 border-border-strong border-t-blue-400 rounded-full animate-spin" />
        ) : dragging ? (
          '📥'
        ) : (
          '📎'
        )}
      </button>

      {toast && (
        <div className="absolute bottom-[110%] left-1/2 -translate-x-1/2 bg-surface-card border border-border-strong rounded-lg px-3 py-1.5 text-[11px] text-text-primary whitespace-nowrap z-50 shadow-xl animate-fade-in">
          {toast}
        </div>
      )}
    </div>
  );
}

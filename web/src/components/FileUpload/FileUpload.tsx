'use client';
import { useRef, useState } from 'react';
import { API_URL } from '@/constants/api';

interface FileUploadProps {
  sessionId: string | null;
  onUploaded: (reference: string, filename: string) => void;
}

export function FileUpload({ sessionId, onUploaded }: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const handleClick = () => {
    if (!uploading) inputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

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
      const reference = data.reference;

      await navigator.clipboard.writeText(reference).catch(() => {});
      showToast(`Copied! Use in chat: ${reference}`);
      onUploaded(reference, file.name);
    } catch {
      showToast('Upload failed. Please try again.');
    } finally {
      setUploading(false);
      // Reset so the same file can be re-selected
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <input
        ref={inputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
      <button
        onClick={handleClick}
        title="Attach file"
        disabled={uploading}
        style={{
          background: 'none',
          border: 'none',
          cursor: uploading ? 'not-allowed' : 'pointer',
          padding: '6px 8px',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: uploading ? '#334155' : '#64748b',
          fontSize: 16,
          transition: 'color 0.2s',
        }}
        onMouseEnter={(e) => {
          if (!uploading) (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.color = uploading ? '#334155' : '#64748b';
        }}
      >
        {uploading ? (
          <span
            style={{
              display: 'inline-block',
              width: 14,
              height: 14,
              border: '2px solid #334155',
              borderTopColor: '#60a5fa',
              borderRadius: '50%',
              animation: 'fileUploadSpin 0.7s linear infinite',
            }}
          />
        ) : (
          '📎'
        )}
      </button>

      {toast && (
        <div
          style={{
            position: 'absolute',
            bottom: '110%',
            left: '50%',
            transform: 'translateX(-50%)',
            background: '#1e1e2e',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: '6px 12px',
            fontSize: 11,
            color: '#e2e8f0',
            whiteSpace: 'nowrap',
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
          }}
        >
          {toast}
        </div>
      )}

      <style>{`
        @keyframes fileUploadSpin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

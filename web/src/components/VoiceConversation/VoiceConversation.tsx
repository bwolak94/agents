'use client';
import { useState, useRef, useCallback, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface VoiceConversationProps {
  sessionId: string | null;
  onClose: () => void;
}

type Status = 'idle' | 'listening' | 'processing' | 'speaking' | 'error';

export function VoiceConversation({ sessionId, onClose }: VoiceConversationProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [error, setError] = useState('');
  const recognitionRef = useRef<{ start(): void; stop(): void; abort(): void } | null>(null);
  const synthRef = useRef<SpeechSynthesisUtterance | null>(null);

  const speak = useCallback((text: string) => {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 1.0;
    utt.pitch = 1.0;
    utt.onstart = () => setStatus('speaking');
    utt.onend = () => setStatus('idle');
    synthRef.current = utt;
    window.speechSynthesis.speak(utt);
  }, []);

  const sendToAgent = useCallback(async (text: string) => {
    setStatus('processing');
    setResponse('');
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      const data = await res.json();
      const reply = data.response ?? 'No response';
      setResponse(reply);
      speak(reply.slice(0, 1000));
    } catch (e) {
      setError(String(e));
      setStatus('error');
    }
  }, [sessionId, speak]);

  const startListening = useCallback(() => {
    const SpeechRecognition =
      (window as typeof window & { SpeechRecognition?: typeof window.SpeechRecognition; webkitSpeechRecognition?: typeof window.SpeechRecognition }).SpeechRecognition ??
      (window as typeof window & { webkitSpeechRecognition?: typeof window.SpeechRecognition }).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setError('Speech recognition is not supported in this browser.');
      setStatus('error');
      return;
    }

    const recognition = new SpeechRecognition() as unknown as Record<string, unknown>;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onstart = () => setStatus('listening');
    recognition.onresult = (event: { results: Array<{ 0: { transcript: string } }> }) => {
      const text = event.results[0][0].transcript;
      setTranscript(text);
      sendToAgent(text);
    };
    recognition.onerror = (event: { error: string }) => {
      setError(event.error);
      setStatus('error');
    };
    recognition.onend = () => {
      if (status === 'listening') setStatus('idle');
    };

    recognitionRef.current = recognition as unknown as { start(): void; stop(): void; abort(): void };
    (recognition as unknown as { start(): void }).start();
  }, [sendToAgent, status]);

  const stopAll = useCallback(() => {
    recognitionRef.current?.abort();
    window.speechSynthesis?.cancel();
    setStatus('idle');
  }, []);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      window.speechSynthesis?.cancel();
    };
  }, []);

  const statusColor: Record<Status, string> = {
    idle: '#475569',
    listening: '#22c55e',
    processing: '#f59e0b',
    speaking: '#3b82f6',
    error: '#ef4444',
  };

  const statusLabel: Record<Status, string> = {
    idle: 'Ready',
    listening: 'Listening...',
    processing: 'Thinking...',
    speaking: 'Speaking...',
    error: 'Error',
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#0f172a', border: '1px solid #334155', borderRadius: 16,
        width: 420, padding: 32, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
          <span style={{ color: '#94a3b8', fontWeight: 600, fontSize: 16 }}>Voice Conversation</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 18 }}>x</button>
        </div>

        {/* Status indicator */}
        <div style={{ textAlign: 'center' }}>
          <div style={{
            width: 80, height: 80, borderRadius: '50%',
            background: statusColor[status] + '22',
            border: `3px solid ${statusColor[status]}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 32,
            animation: status === 'listening' ? 'pulse 1s infinite' : 'none',
          }}>
            {status === 'listening' ? 'mic' : status === 'speaking' ? 'vol' : status === 'processing' ? '...' : 'mic'}
          </div>
          <div style={{ color: statusColor[status], fontSize: 13, marginTop: 8 }}>{statusLabel[status]}</div>
        </div>

        {/* Transcript */}
        {transcript && (
          <div style={{ width: '100%', background: '#1e293b', borderRadius: 8, padding: '10px 14px' }}>
            <div style={{ color: '#64748b', fontSize: 11, marginBottom: 4 }}>You said:</div>
            <div style={{ color: '#e2e8f0', fontSize: 13 }}>{transcript}</div>
          </div>
        )}

        {/* Response */}
        {response && (
          <div style={{ width: '100%', background: '#1e293b', borderRadius: 8, padding: '10px 14px', maxHeight: 160, overflowY: 'auto' }}>
            <div style={{ color: '#64748b', fontSize: 11, marginBottom: 4 }}>Agent:</div>
            <div style={{ color: '#94a3b8', fontSize: 13, whiteSpace: 'pre-wrap' }}>{response}</div>
          </div>
        )}

        {/* Error */}
        {error && <div style={{ color: '#f87171', fontSize: 13 }}>{error}</div>}

        {/* Controls */}
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={status === 'idle' || status === 'error' ? startListening : stopAll}
            style={{
              background: status === 'listening' ? '#dc2626' : '#2563eb',
              color: '#fff', border: 'none', borderRadius: 8,
              padding: '10px 24px', cursor: 'pointer', fontSize: 14, fontWeight: 600,
            }}
          >
            {status === 'listening' ? 'Stop' : 'Speak'}
          </button>
          {status === 'speaking' && (
            <button
              onClick={() => { window.speechSynthesis?.cancel(); setStatus('idle'); }}
              style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 8, padding: '10px 16px', cursor: 'pointer', fontSize: 13 }}
            >
              Stop speaking
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

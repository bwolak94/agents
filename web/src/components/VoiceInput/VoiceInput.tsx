'use client';
import { useEffect, useRef, useState } from 'react';

interface VoiceInputProps {
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

export function VoiceInput({ onTranscript, disabled = false }: VoiceInputProps) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(true);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    const SR = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!SR) {
      setSupported(false);
      return;
    }

    const recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = Array.from(event.results)
        .map((r: SpeechRecognitionResult) => r[0].transcript)
        .join(' ')
        .trim();
      if (transcript) onTranscript(transcript);
    };

    recognition.onend = () => {
      setListening(false);
    };

    recognition.onerror = () => {
      setListening(false);
    };

    recognitionRef.current = recognition;
  }, [onTranscript]);

  const handleClick = () => {
    if (!supported || disabled) return;

    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
    } else {
      recognitionRef.current?.start();
      setListening(true);
    }
  };

  const buttonColor = listening ? '#dc2626' : '#64748b';
  const hoverColor = listening ? '#ef4444' : '#94a3b8';

  return (
    <>
      <style>{`
        @keyframes voicePulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.6); }
          50% { box-shadow: 0 0 0 8px rgba(220, 38, 38, 0); }
        }
      `}</style>
      <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
        <button
          onClick={handleClick}
          disabled={disabled || !supported}
          title={!supported ? 'Voice input not supported' : listening ? 'Stop listening' : 'Start voice input'}
          style={{
            background: 'none',
            border: 'none',
            cursor: disabled || !supported ? 'not-allowed' : 'pointer',
            padding: '6px 8px',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: !supported || disabled ? '#334155' : buttonColor,
            fontSize: 16,
            transition: 'color 0.2s',
            animation: listening ? 'voicePulse 1.2s ease-in-out infinite' : 'none',
          }}
          onMouseEnter={(e) => {
            if (!disabled && supported)
              (e.currentTarget as HTMLButtonElement).style.color = hoverColor;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.color =
              !supported || disabled ? '#334155' : buttonColor;
          }}
        >
          🎤
        </button>

        {!supported && (
          <div
            style={{
              position: 'absolute',
              bottom: '110%',
              left: '50%',
              transform: 'translateX(-50%)',
              background: '#1e1e2e',
              border: '1px solid #334155',
              borderRadius: 8,
              padding: '5px 10px',
              fontSize: 11,
              color: '#94a3b8',
              whiteSpace: 'nowrap',
              zIndex: 100,
              pointerEvents: 'none',
              opacity: 0,
              transition: 'opacity 0.2s',
            }}
            className="voice-tooltip"
          >
            Voice input not supported
          </div>
        )}
      </div>
    </>
  );
}

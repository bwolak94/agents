import type { CSSProperties } from 'react';

interface SpeechBubbleProps {
  text: string;
  color: string;
}

const MAX_TEXT_LENGTH = 24;

export function SpeechBubble({ text, color }: SpeechBubbleProps) {
  const containerStyle: CSSProperties = {
    position: 'absolute',
    bottom: 'calc(100% + 6px)',
    left: '50%',
    transform: 'translateX(-50%)',
    background: '#0d0d1a',
    border: `1px solid ${color}`,
    borderRadius: 4,
    padding: '4px 8px',
    fontSize: 7,
    fontFamily: "'Press Start 2P', monospace",
    color,
    whiteSpace: 'nowrap',
    maxWidth: 180,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    zIndex: 20,
    pointerEvents: 'none',
    boxShadow: `0 0 8px ${color}44`,
  };

  const arrowStyle: CSSProperties = {
    position: 'absolute',
    bottom: -5,
    left: '50%',
    transform: 'translateX(-50%)',
    width: 0,
    height: 0,
    borderLeft: '4px solid transparent',
    borderRight: '4px solid transparent',
    borderTop: `5px solid ${color}`,
  };

  const displayText = text.length > MAX_TEXT_LENGTH ? text.slice(0, MAX_TEXT_LENGTH) + '…' : text;

  return (
    <div className="bubble-pop" style={containerStyle}>
      {displayText}
      <div style={arrowStyle} />
    </div>
  );
}

import React from "react";

interface SpinnerProps {
  size?: number;
  color?: string;
}

export function Spinner({ size = 24, color = "currentColor" }: SpinnerProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         style={{ animation: "ui-spin 0.8s linear infinite" }}>
      <circle cx="12" cy="12" r="10" stroke={color} strokeWidth="3" strokeDasharray="30 60" />
      <style>{`@keyframes ui-spin { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );
}

import React from "react";
import { colors } from "./colors";

interface CardProps {
  children: React.ReactNode;
  title?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function Card({ children, title, style }: CardProps) {
  return (
    <div style={{
      background: colors.surface,
      border: `1px solid ${colors.border}`,
      borderRadius: "0.75rem",
      padding: "1rem 1.25rem",
      ...style,
    }}>
      {title && (
        <h3 style={{ margin: "0 0 0.75rem", fontSize: "0.875rem", fontWeight: 600, color: colors.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}

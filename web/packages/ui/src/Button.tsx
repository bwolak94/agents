import React from "react";
import { colors } from "./colors";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  style,
  ...props
}: ButtonProps) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "0.375rem",
    borderRadius: "0.5rem",
    fontWeight: 500,
    border: "1px solid transparent",
    cursor: disabled || loading ? "not-allowed" : "pointer",
    opacity: disabled || loading ? 0.6 : 1,
    transition: "all 0.15s ease",
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    primary:   { background: colors.primary,  color: "#fff" },
    secondary: { background: colors.surface,  color: colors.text, borderColor: colors.border },
    danger:    { background: colors.danger,   color: "#fff" },
    ghost:     { background: "transparent",   color: colors.textMuted },
  };

  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: { padding: "0.25rem 0.625rem", fontSize: "0.8125rem" },
    md: { padding: "0.5rem 1rem",      fontSize: "0.875rem" },
    lg: { padding: "0.75rem 1.5rem",   fontSize: "1rem" },
  };

  return (
    <button
      disabled={disabled || loading}
      style={{ ...base, ...variantStyles[variant], ...sizeStyles[size], ...style }}
      {...props}
    >
      {loading && <Spinner size={14} />}
      {children}
    </button>
  );
}

// Inline spinner for button loading state
function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         style={{ animation: "spin 0.8s linear infinite" }}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="30 60" />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );
}

import React from "react";
import { colors } from "./colors";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "primary";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
}

const variantMap: Record<BadgeVariant, { bg: string; color: string }> = {
  default: { bg: colors.border,   color: colors.text },
  primary: { bg: "#312e81",       color: "#a5b4fc" },
  success: { bg: "#14532d",       color: "#86efac" },
  warning: { bg: "#713f12",       color: "#fde68a" },
  danger:  { bg: "#7f1d1d",       color: "#fca5a5" },
};

export function Badge({ children, variant = "default" }: BadgeProps) {
  const { bg, color } = variantMap[variant];
  return (
    <span style={{
      display: "inline-flex",
      alignItems: "center",
      padding: "0.125rem 0.5rem",
      borderRadius: "9999px",
      fontSize: "0.75rem",
      fontWeight: 500,
      background: bg,
      color,
    }}>
      {children}
    </span>
  );
}

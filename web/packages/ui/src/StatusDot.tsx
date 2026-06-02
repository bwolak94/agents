import React from "react";
import { colors } from "./colors";

type Status = "healthy" | "unhealthy" | "unknown" | "running" | "waiting";

const statusColors: Record<Status, string> = {
  healthy:   colors.success,
  running:   colors.primary,
  waiting:   colors.warning,
  unhealthy: colors.danger,
  unknown:   colors.muted,
};

interface StatusDotProps {
  status: Status;
  label?: string;
}

export function StatusDot({ status, label }: StatusDotProps) {
  const color = statusColors[status] || colors.muted;
  const pulse = status === "running" || status === "healthy";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.375rem" }}>
      <span style={{
        display: "inline-block",
        width: 8, height: 8,
        borderRadius: "50%",
        background: color,
        boxShadow: pulse ? `0 0 0 2px ${color}40` : undefined,
        animation: pulse ? "pulse-dot 2s ease-in-out infinite" : undefined,
      }} />
      {label && <span style={{ fontSize: "0.8125rem", color }}>{label}</span>}
      <style>{`@keyframes pulse-dot { 0%,100%{opacity:1} 50%{opacity:.5} }`}</style>
    </span>
  );
}

// Design tokens — shared across all MFEs
export const colors = {
  primary:    "#6366f1",  // indigo-500
  secondary:  "#8b5cf6",  // violet-500
  success:    "#22c55e",  // green-500
  warning:    "#f59e0b",  // amber-500
  danger:     "#ef4444",  // red-500
  muted:      "#6b7280",  // gray-500
  bg:         "#0f172a",  // slate-900
  surface:    "#1e293b",  // slate-800
  border:     "#334155",  // slate-700
  text:       "#f1f5f9",  // slate-100
  textMuted:  "#94a3b8",  // slate-400
} as const;

export type Color = keyof typeof colors;

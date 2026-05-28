/**
 * #21 — Shared Button component, now used throughout the main app.
 * Uses design-system class strings so it works with or without Tailwind.
 */
import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

const VARIANT_CLASSES: Record<string, string> = {
  primary:   'bg-[#2563eb] text-white hover:bg-[#1d4ed8] border-transparent',
  secondary: 'bg-[#1e293b] text-[#94a3b8] hover:text-[#e2e8f0] border-[#334155]',
  danger:    'bg-[#7f1d1d] text-[#fca5a5] hover:bg-[#991b1b] border-[#450a0a]',
  ghost:     'bg-transparent text-[#64748b] hover:text-[#94a3b8] border-transparent',
};

const SIZE_CLASSES: Record<string, string> = {
  sm: 'px-2.5 py-1   text-[13px]',
  md: 'px-4   py-2   text-sm',
  lg: 'px-6   py-3   text-base',
};

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className = '',
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <button
      disabled={isDisabled}
      className={[
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium',
        'border transition-all duration-150 outline-none',
        'focus-visible:ring-2 focus-visible:ring-[#2563eb]',
        isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      ].join(' ')}
      {...props}
    >
      {loading && <ButtonSpinner />}
      {children}
    </button>
  );
}

function ButtonSpinner() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none"
      style={{ animation: 'spin 0.8s linear infinite' }}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="30 60" />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </svg>
  );
}

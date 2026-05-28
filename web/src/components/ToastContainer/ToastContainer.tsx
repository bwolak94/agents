'use client';
import type { Toast, ToastType } from '@/hooks/useToast';

const TYPE_STYLES: Record<ToastType, string> = {
  info:    'bg-surface-card border-border-strong text-text-primary',
  success: 'bg-green-950 border-green-800 text-green-300',
  error:   'bg-red-950 border-red-800 text-red-300',
  warning: 'bg-yellow-950 border-yellow-800 text-yellow-300',
};

const TYPE_ICON: Record<ToastType, string> = {
  info:    'ℹ',
  success: '✓',
  error:   '✕',
  warning: '⚠',
};

interface ToastContainerProps {
  toasts: Toast[];
  onRemove: (id: string) => void;
}

export function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[1000] flex flex-col gap-2 pointer-events-none">
      {toasts.map(t => (
        <div
          key={t.id}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border shadow-xl text-sm animate-fade-in pointer-events-auto max-w-sm ${TYPE_STYLES[t.type]}`}
        >
          <span className="font-bold">{TYPE_ICON[t.type]}</span>
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => onRemove(t.id)}
            className="opacity-60 hover:opacity-100 transition-opacity text-base leading-none ml-1 cursor-pointer border-none bg-transparent"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

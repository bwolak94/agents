/**
 * #27 — Blinking cursor shown at the end of a streaming response.
 * Extracted from ChatView to avoid inline animation strings.
 */
export function StreamingCursor() {
  return (
    <span
      aria-hidden="true"
      className="inline-block w-2 h-[14px] bg-text-faint rounded-sm ml-0.5 align-middle animate-dot-bounce"
    />
  );
}

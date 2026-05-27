import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ErrorBoundary } from '@/components/ErrorBoundary/ErrorBoundary';

export const metadata: Metadata = {
  title: 'Agent System',
  description: 'Multi-LLM Agent System',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, padding: 0, background: '#0a0a1a' }}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </body>
    </html>
  );
}

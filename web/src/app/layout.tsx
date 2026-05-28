import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ErrorBoundary } from '@/components/ErrorBoundary/ErrorBoundary';
import './globals.css';

export const metadata: Metadata = {
  title: 'Agent System',
  description: 'Multi-LLM Agent System — Claude, Gemini, Ollama',
  manifest: '/manifest.json',
  themeColor: '#2563eb',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'Agent System',
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      </head>
      <body>
        <ErrorBoundary>{children}</ErrorBoundary>
      </body>
    </html>
  );
}

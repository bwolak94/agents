'use client';
import { Component, type ReactNode, type ErrorInfo } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function reportClientError(error: Error, info: ErrorInfo, component?: string) {
  try {
    await fetch(`${API_BASE}/logs/client-error`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: error.message.slice(0, 500),
        stack: (error.stack ?? '').slice(0, 5000),
        component: (component ?? info.componentStack?.split('\n')[1] ?? '').slice(0, 200),
        url: typeof window !== 'undefined' ? window.location.href.slice(0, 500) : '',
        user_agent: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 300) : '',
      }),
    });
  } catch {
    // Telemetry must never throw
  }
}

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  component?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary] Uncaught error:', error, info.componentStack);
    reportClientError(error, info, this.props.component);
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100vh',
              background: '#0a0a1a',
              color: '#e2e8f0',
              gap: 16,
              padding: 32,
            }}
          >
            <div style={{ fontSize: 48 }}>⚠️</div>
            <h2 style={{ margin: 0, fontSize: 18, color: '#f87171' }}>Something went wrong</h2>
            <pre
              style={{
                background: '#1e1e2e',
                border: '1px solid #334155',
                borderRadius: 8,
                padding: '12px 16px',
                fontSize: 12,
                color: '#94a3b8',
                maxWidth: 600,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {this.state.error.message}
            </pre>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                background: '#2563eb',
                color: '#e2e8f0',
                border: 'none',
                borderRadius: 8,
                padding: '8px 20px',
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              Try again
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

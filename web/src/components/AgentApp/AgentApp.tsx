'use client';
import { useState, useCallback } from 'react';
import { GAME_CSS } from '@/constants/gameStyles';
import { useSession } from '@/hooks/useSession';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useChatHistory } from '@/hooks/useChatHistory';
import { useTheme } from '@/hooks/useTheme';
import { Header } from '@/components/Header/Header';
import type { ViewId } from '@/components/Header/Header';
import { AgentPanel } from '@/components/AgentPanel/AgentPanel';
import { ChatView } from '@/components/ChatView/ChatView';
import { EventLog } from '@/components/EventLog/EventLog';
import { AnalyticsDashboard } from '@/components/AnalyticsDashboard/AnalyticsDashboard';
import { ChatHistorySidebar } from '@/components/ChatHistorySidebar/ChatHistorySidebar';
import { CommandPalette } from '@/components/CommandPalette/CommandPalette';
import { MemoryInspector } from '@/components/MemoryInspector/MemoryInspector';
import { ErrorBoundary } from '@/components/ErrorBoundary/ErrorBoundary';
import { API_URL } from '@/constants/api';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';

export function AgentApp() {
  const { sessionId, switchSession, newSession } = useSession();
  const { agents, events, wsStatus, costs, stats, clearAgents } = useWebSocket(sessionId);
  const { messages, setMessages, historyLoading } = useChatHistory(sessionId);
  const { theme, toggleTheme } = useTheme();
  const [view, setView] = useState<ViewId>('chat');
  const [sidebarRefresh, setSidebarRefresh] = useState(0);

  const bgColor = theme === 'dark' ? '#0a0a1a' : '#f8fafc';
  const textColor = theme === 'dark' ? '#e2e8f0' : '#1e293b';

  const handleNewSession = useCallback(() => {
    newSession();
    setMessages([]);
    setSidebarRefresh((n) => n + 1);
    clearAgents(); // #16 — clear stale agent state from previous session
  }, [newSession, setMessages, clearAgents]);

  const handleSelectSession = useCallback((id: string) => {
    switchSession(id);
    setMessages([]);
    clearAgents(); // #16
  }, [switchSession, setMessages, clearAgents]);

  const handleClearChat = useCallback(async () => {
    if (!sessionId) return;
    if (!window.confirm('Clear all messages in this chat?')) return;
    await fetch(`${API_URL}/history/${sessionId}`, { method: 'DELETE' });
    setMessages([]);
    setSidebarRefresh((n) => n + 1);
  }, [sessionId, setMessages]);

  // #15 — only refresh sidebar after assistant response (not on user message add)
  const handleMessagesChange: Dispatch<SetStateAction<ChatMessage[]>> = useCallback((updater) => {
    setMessages((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      // Refresh sidebar only when an assistant/error message is added
      const lastMsg = next[next.length - 1];
      if (lastMsg && lastMsg.role !== 'user') {
        setSidebarRefresh((n) => n + 1);
      }
      return next;
    });
  }, [setMessages]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: bgColor,
        color: textColor,
        overflow: 'hidden',
      }}
    >
      <style>{GAME_CSS}</style>

      <CommandPalette
        onViewChange={setView}
        onNewSession={handleNewSession}
        sessionId={sessionId}
      />

      <Header
        wsStatus={wsStatus}
        stats={stats}
        costs={costs}
        view={view}
        onViewChange={setView}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Chat history sidebar */}
        <ChatHistorySidebar
          activeSessionId={sessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          refreshTrigger={sidebarRefresh}
        />

        {/* Left — agents */}
        <div
          style={{
            width: 280,
            flexShrink: 0,
            borderRight: '1px solid #1a1a2e',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <AgentPanel agents={agents} />
        </div>

        {/* Right — main content, each view wrapped in its own error boundary */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {view === 'chat' && (
            <ErrorBoundary fallback={<PanelError label="Chat" />}>
              <ChatView
                sessionId={sessionId}
                messages={messages}
                setMessages={handleMessagesChange}
                historyLoading={historyLoading}
                onClearChat={handleClearChat}
              />
            </ErrorBoundary>
          )}
          {view === 'analytics' && (
            <ErrorBoundary fallback={<PanelError label="Analytics" />}>
              <AnalyticsDashboard />
            </ErrorBoundary>
          )}
          {view === 'memory' && (
            <ErrorBoundary fallback={<PanelError label="Memory" />}>
              <MemoryInspector sessionId={sessionId} />
            </ErrorBoundary>
          )}
        </div>
      </div>

      <EventLog events={events} />
    </div>
  );
}

function PanelError({ label }: { label: string }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, color: '#f87171' }}>
      <span style={{ fontSize: 28 }}>⚠️</span>
      <span style={{ fontSize: 13 }}>{label} panel encountered an error.</span>
      <button onClick={() => window.location.reload()} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 11, padding: '4px 12px' }}>Reload</button>
    </div>
  );
}

'use client';
import { useState, useCallback } from 'react';
import { GAME_CSS } from '@/constants/gameStyles';
import { useSession } from '@/hooks/useSession';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useChatHistory } from '@/hooks/useChatHistory';
import { Header } from '@/components/Header/Header';
import type { ViewId } from '@/components/Header/Header';
import { AgentPanel } from '@/components/AgentPanel/AgentPanel';
import { ChatView } from '@/components/ChatView/ChatView';
import { EventLog } from '@/components/EventLog/EventLog';
import { AnalyticsDashboard } from '@/components/AnalyticsDashboard/AnalyticsDashboard';
import { ChatHistorySidebar } from '@/components/ChatHistorySidebar/ChatHistorySidebar';
import { API_URL } from '@/constants/api';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';

export function AgentApp() {
  const { sessionId, switchSession, newSession } = useSession();
  const { agents, events, wsStatus, costs, stats, clearAgents } = useWebSocket(sessionId);
  const { messages, setMessages, historyLoading } = useChatHistory(sessionId);
  const [view, setView] = useState<ViewId>('chat');
  const [sidebarRefresh, setSidebarRefresh] = useState(0);

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
        background: '#0a0a1a',
        color: '#e2e8f0',
        overflow: 'hidden',
      }}
    >
      <style>{GAME_CSS}</style>

      <Header
        wsStatus={wsStatus}
        stats={stats}
        costs={costs}
        view={view}
        onViewChange={setView}
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

        {/* Right — main content */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {view === 'chat' && (
            <ChatView
              sessionId={sessionId}
              messages={messages}
              setMessages={handleMessagesChange}
              historyLoading={historyLoading}
              onClearChat={handleClearChat}
            />
          )}
          {view === 'analytics' && <AnalyticsDashboard sessionId={sessionId} />}
        </div>
      </div>

      <EventLog events={events} />
    </div>
  );
}

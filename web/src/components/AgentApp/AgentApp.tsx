'use client';
import { useState } from 'react';
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

export function AgentApp() {
  const { sessionId, switchSession, newSession } = useSession();
  const { agents, events, wsStatus, costs, stats } = useWebSocket(sessionId);
  const { messages, setMessages } = useChatHistory(sessionId);
  const [view, setView] = useState<ViewId>('chat');
  const [sidebarRefresh, setSidebarRefresh] = useState(0);

  const handleNewSession = () => {
    newSession();
    setMessages([]);
    setSidebarRefresh((n) => n + 1);
  };

  const handleSelectSession = (id: string) => {
    switchSession(id);
    setMessages([]);
  };

  // Refresh sidebar after sending a message (new session gets a first message)
  const handleMessagesChange: typeof setMessages = (updater) => {
    setMessages(updater);
    setSidebarRefresh((n) => n + 1);
  };

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

      {/* Top bar */}
      <Header
        wsStatus={wsStatus}
        stats={stats}
        costs={costs}
        view={view}
        onViewChange={setView}
      />

      {/* Main split pane */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Chat history sidebar */}
        <ChatHistorySidebar
          activeSessionId={sessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          refreshTrigger={sidebarRefresh}
        />

        {/* Left — agents (always visible) */}
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

        {/* Right — main content area, switches based on view */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {view === 'chat' && (
            <ChatView sessionId={sessionId} messages={messages} setMessages={handleMessagesChange} />
          )}
          {view === 'analytics' && <AnalyticsDashboard sessionId={sessionId} />}
        </div>
      </div>

      {/* Bottom — timeline */}
      <EventLog events={events} />
    </div>
  );
}

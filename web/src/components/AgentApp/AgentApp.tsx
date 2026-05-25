'use client';
import { GAME_CSS } from '@/constants/gameStyles';
import { useSession } from '@/hooks/useSession';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useChatHistory } from '@/hooks/useChatHistory';
import { Header } from '@/components/Header/Header';
import { AgentPanel } from '@/components/AgentPanel/AgentPanel';
import { ChatView } from '@/components/ChatView/ChatView';
import { EventLog } from '@/components/EventLog/EventLog';

export function AgentApp() {
  const sessionId = useSession();
  const { agents, events, wsStatus, costs, stats } = useWebSocket(sessionId);
  const { messages, setMessages } = useChatHistory(sessionId);

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
      <Header wsStatus={wsStatus} stats={stats} costs={costs} />

      {/* Main split pane */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Left — agents */}
        <div
          style={{
            width: 320,
            flexShrink: 0,
            borderRight: '1px solid #1a1a2e',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <AgentPanel agents={agents} />
        </div>

        {/* Right — chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <ChatView sessionId={sessionId} messages={messages} setMessages={setMessages} />
        </div>
      </div>

      {/* Bottom — timeline */}
      <EventLog events={events} />
    </div>
  );
}

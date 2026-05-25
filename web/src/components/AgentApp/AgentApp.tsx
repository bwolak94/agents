'use client';
import { useState } from 'react';
import { GAME_CSS } from '@/constants/gameStyles';
import { useSession } from '@/hooks/useSession';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useChatHistory } from '@/hooks/useChatHistory';
import { Header, type ViewId } from '@/components/Header/Header';
import { WorldView } from '@/components/WorldView/WorldView';
import { ChatView } from '@/components/ChatView/ChatView';

export function AgentApp() {
  const [view, setView] = useState<ViewId>('world');

  const sessionId = useSession();
  const { agents, events, wsStatus, costs, stats } = useWebSocket(sessionId);
  const { messages, setMessages } = useChatHistory(sessionId);

  const activeAgentCount = Object.values(agents).filter((a) => a.status !== 'fading').length;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: '#0a0a1a',
        color: '#e2e8f0',
      }}
    >
      <style>{GAME_CSS}</style>

      <Header
        view={view}
        onViewChange={setView}
        wsStatus={wsStatus}
        activeAgentCount={activeAgentCount}
      />

      {/* Both views always mounted — CSS controls visibility to preserve state */}
      <div
        style={{
          flex: 1,
          display: view === 'world' ? 'flex' : 'none',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <WorldView
          agents={agents}
          stats={stats}
          costs={costs}
          events={events}
          wsStatus={wsStatus}
        />
      </div>

      <div
        style={{
          flex: 1,
          display: view === 'chat' ? 'flex' : 'none',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <ChatView sessionId={sessionId} messages={messages} setMessages={setMessages} />
      </div>
    </div>
  );
}

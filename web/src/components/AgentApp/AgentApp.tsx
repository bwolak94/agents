'use client';
import { useState, useCallback, useRef, useEffect } from 'react';
import { useSession } from '@/hooks/useSession';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useChatHistory } from '@/hooks/useChatHistory';
import { useTheme } from '@/hooks/useTheme';
import { useLocalStorage } from '@/hooks/useLocalStorage';
import { useToast } from '@/hooks/useToast';
import { Header } from '@/components/Header/Header';
import type { ViewId } from '@/components/Header/Header';
import { AgentPanel } from '@/components/AgentPanel/AgentPanel';
import { ChatView } from '@/components/ChatView/ChatView';
import { EventLog } from '@/components/EventLog/EventLog';
import { AnalyticsDashboard } from '@/components/AnalyticsDashboard/AnalyticsDashboard';
import { ChatHistorySidebar } from '@/components/ChatHistorySidebar/ChatHistorySidebar';
import { CommandPalette } from '@/components/CommandPalette/CommandPalette';
import { MemoryInspector } from '@/components/MemoryInspector/MemoryInspector';
import { ConfirmModal } from '@/components/ConfirmModal/ConfirmModal';
import { ToastContainer } from '@/components/ToastContainer/ToastContainer';
import { KeyboardShortcuts } from '@/components/KeyboardShortcuts/KeyboardShortcuts';
import { ErrorBoundary } from '@/components/ErrorBoundary/ErrorBoundary';
import { ArtifactPanel } from '@/components/ArtifactPanel/ArtifactPanel';
import { BranchView } from '@/components/BranchView/BranchView';
import { PluginMarketplace } from '@/components/PluginMarketplace/PluginMarketplace';
import { ABTestView } from '@/components/ABTestView/ABTestView';
import { VoiceConversation } from '@/components/VoiceConversation/VoiceConversation';
import { CostTrackerHUD } from '@/components/CostTrackerHUD/CostTrackerHUD';
import { SideBySideView } from '@/components/SideBySideView/SideBySideView';
import { KnowledgeGraph } from '@/components/KnowledgeGraph/KnowledgeGraph';
import { API_URL } from '@/constants/api';
import type { ChatMessage } from '@/types/chat';
import type { Dispatch, SetStateAction } from 'react';

const COST_BUDGET = typeof process !== 'undefined' ? parseFloat(process.env.NEXT_PUBLIC_COST_BUDGET_USD ?? '0') : 0;

// #30 — Persist layout preferences
interface UiPrefs {
  view: ViewId;
  eventLogCollapsed: boolean;
  sidebarCollapsed: boolean;
  agentPanelCollapsed: boolean;
  artifactPanelCollapsed: boolean;
}

const DEFAULT_PREFS: UiPrefs = {
  view: 'chat',
  eventLogCollapsed: false,
  sidebarCollapsed: false,
  agentPanelCollapsed: false,
  artifactPanelCollapsed: false,
};

function PanelError({ label }: { label: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 text-red-400">
      <span className="text-3xl">⚠️</span>
      <span className="text-sm">{label} panel encountered an error.</span>
      <button onClick={() => window.location.reload()}
        className="bg-surface-active border border-border-strong rounded-md text-text-secondary text-xs px-3 py-1 cursor-pointer hover:text-text-primary transition-colors">
        Reload
      </button>
    </div>
  );
}

export function AgentApp() {
  const { sessionId, switchSession, newSession } = useSession();
  const { agents, events, wsStatus, costs, stats, clearAgents } = useWebSocket(sessionId);

  // Offline banner: show after 5 seconds of disconnected state
  const offlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showOfflineBanner, setShowOfflineBanner] = useState(false);
  useEffect(() => {
    if (wsStatus === 'offline') {
      offlineTimerRef.current = setTimeout(() => setShowOfflineBanner(true), 5000);
    } else {
      if (offlineTimerRef.current) clearTimeout(offlineTimerRef.current);
      setShowOfflineBanner(false);
    }
    return () => { if (offlineTimerRef.current) clearTimeout(offlineTimerRef.current); };
  }, [wsStatus]);
  const { messages, setMessages, historyLoading } = useChatHistory(sessionId);
  const { theme, toggleTheme } = useTheme();
  const { toasts, addToast, removeToast } = useToast();

  // #30 — Persist layout preferences across page reloads
  const [prefs, setPrefs] = useLocalStorage<UiPrefs>('ui-prefs', DEFAULT_PREFS);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [confirmClear, setConfirmClear]     = useState(false);
  const [showShortcuts, setShowShortcuts]   = useState(false);
  const [showVoice, setShowVoice]           = useState(false);

  // Ctrl+? to open shortcuts; Escape to close all overlays (FE23)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '?') { e.preventDefault(); setShowShortcuts(s => !s); }
      if (e.key === 'Escape') {
        setShowShortcuts(false);
        setShowVoice(false);
        setConfirmClear(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const setView               = (v: ViewId) => setPrefs(p => ({ ...p, view: v }));
  const toggleEventLog        = () => setPrefs(p => ({ ...p, eventLogCollapsed: !p.eventLogCollapsed }));
  const toggleSidebar         = () => setPrefs(p => ({ ...p, sidebarCollapsed: !p.sidebarCollapsed }));
  const toggleAgentPanel      = () => setPrefs(p => ({ ...p, agentPanelCollapsed: !p.agentPanelCollapsed }));
  const toggleArtifactPanel   = () => setPrefs(p => ({ ...p, artifactPanelCollapsed: !p.artifactPanelCollapsed }));

  const handleNewSession = useCallback(() => {
    newSession();
    setMessages([]);
    setSidebarRefresh((n) => n + 1);
    clearAgents();
  }, [newSession, setMessages, clearAgents]);

  const handleSelectSession = useCallback((id: string) => {
    switchSession(id);
    setMessages([]);
    clearAgents();
  }, [switchSession, setMessages, clearAgents]);

  const handleClearChat = useCallback(async () => {
    if (!sessionId) return;
    await fetch(`${API_URL}/history/${sessionId}`, { method: 'DELETE' });
    setMessages([]);
    setSidebarRefresh((n) => n + 1);
    setConfirmClear(false);
  }, [sessionId, setMessages]);

  const handleMessagesChange: Dispatch<SetStateAction<ChatMessage[]>> = useCallback((updater) => {
    setMessages((prev) => {
      const next    = typeof updater === 'function' ? updater(prev) : updater;
      const lastMsg = next[next.length - 1];
      if (lastMsg && lastMsg.role !== 'user') setSidebarRefresh((n) => n + 1);
      return next;
    });
  }, [setMessages]);

  return (
    <>
    <div className="flex flex-col h-screen bg-surface-base text-text-primary overflow-hidden">

      <KeyboardShortcuts open={showShortcuts} onClose={() => setShowShortcuts(false)} />
      <ToastContainer toasts={toasts} onRemove={removeToast} />

      {/* Offline banner — shown after 5s of WS disconnect */}
      {showOfflineBanner && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-red-900/90 text-red-100 text-xs text-center py-1.5 flex items-center justify-center gap-2">
          <span>Connection lost. Reconnecting…</span>
          <button
            onClick={() => window.location.reload()}
            className="underline hover:no-underline"
          >
            Reload
          </button>
        </div>
      )}

      {/* #25 — ConfirmModal for clear chat (replaces window.confirm) */}
      {confirmClear && (
        <ConfirmModal
          message="Clear all messages in this chat? This cannot be undone."
          confirmLabel="Clear chat"
          danger
          onConfirm={handleClearChat}
          onCancel={() => setConfirmClear(false)}
        />
      )}

      <CommandPalette onViewChange={setView} onNewSession={handleNewSession} onSelectSession={handleSelectSession} sessionId={sessionId} />
      {showVoice && <VoiceConversation sessionId={sessionId} onClose={() => setShowVoice(false)} />}

      <Header
        wsStatus={wsStatus}
        stats={stats}
        costs={costs}
        view={prefs.view}
        onViewChange={setView}
        theme={theme}
        onToggleTheme={toggleTheme}
        onVoice={() => setShowVoice(true)}
      />

      {/* #18 — Main layout: three columns with collapsible sidebars */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* #20 — Chat history sidebar (collapsible) */}
        <ChatHistorySidebar
          activeSessionId={sessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          refreshTrigger={sidebarRefresh}
          collapsed={prefs.sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
        />

        {/* #20 — Agent panel (collapsible) */}
        <AgentPanel
          agents={agents}
          collapsed={prefs.agentPanelCollapsed}
          onToggleCollapse={toggleAgentPanel}
        />

        {/* Main content area */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* Panel content */}
          <div className="flex-1 overflow-hidden flex flex-col min-h-0">
            {prefs.view === 'chat' && (
              <ErrorBoundary fallback={<PanelError label="Chat" />}>
                <ChatView
                  sessionId={sessionId}
                  messages={messages}
                  setMessages={handleMessagesChange}
                  historyLoading={historyLoading}
                  onClearChat={() => setConfirmClear(true)}
                />
              </ErrorBoundary>
            )}
            {prefs.view === 'analytics' && (
              <ErrorBoundary fallback={<PanelError label="Analytics" />}>
                <AnalyticsDashboard />
              </ErrorBoundary>
            )}
            {prefs.view === 'memory' && (
              <ErrorBoundary fallback={<PanelError label="Memory" />}>
                <MemoryInspector sessionId={sessionId} />
              </ErrorBoundary>
            )}
            {prefs.view === 'branch' && (
              <ErrorBoundary fallback={<PanelError label="Branch" />}>
                <BranchView
                  messages={messages}
                  sessionId={sessionId}
                  onNewSession={handleSelectSession}
                />
              </ErrorBoundary>
            )}
            {prefs.view === 'plugins' && (
              <ErrorBoundary fallback={<PanelError label="Plugins" />}>
                <PluginMarketplace />
              </ErrorBoundary>
            )}
            {prefs.view === 'ab-test' && (
              <ErrorBoundary fallback={<PanelError label="A/B Test" />}>
                <ABTestView />
              </ErrorBoundary>
            )}
            {prefs.view === 'side-by-side' && (
              <ErrorBoundary fallback={<PanelError label="Side-by-Side" />}>
                <SideBySideView />
              </ErrorBoundary>
            )}
            {prefs.view === 'graph' && (
              <ErrorBoundary fallback={<PanelError label="Knowledge Graph" />}>
                <KnowledgeGraph sessionId={sessionId || 'default'} />
              </ErrorBoundary>
            )}
          </div>

          {/* #19 — EventLog as collapsible drawer */}
          <EventLog
            events={events}
            collapsed={prefs.eventLogCollapsed}
            onToggle={toggleEventLog}
          />
        </div>

        {/* Artifact panel — only in chat view */}
        {prefs.view === 'chat' && (
          <ErrorBoundary fallback={null}>
            <ArtifactPanel
              messages={messages}
              collapsed={prefs.artifactPanelCollapsed}
              onToggle={toggleArtifactPanel}
            />
          </ErrorBoundary>
        )}
      </div>
    </div>

    {/* F5 — Live cost tracker HUD (fixed bottom-right) */}
    <CostTrackerHUD budgetUsd={COST_BUDGET} />
    </>
  );
}

import type { Stats, Costs } from '@/types/chat';
import type { WsStatus } from '@/hooks/useWebSocket';
import type { Theme } from '@/hooks/useTheme';

export type ViewId = 'chat' | 'analytics' | 'memory' | 'branch' | 'plugins' | 'ab-test';

interface HeaderProps {
  wsStatus: WsStatus;
  stats: Stats;
  costs: Costs | null;
  view: ViewId;
  onViewChange: (view: ViewId) => void;
  theme?: Theme;
  onToggleTheme?: () => void;
  onVoice?: () => void;
}

const WS_STATUS_CONFIG: Record<WsStatus, { color: string; label: string }> = {
  connected: { color: 'text-accent-green', label: 'Live' },
  connecting: { color: 'text-accent-yellow', label: 'Connecting' },
  offline:    { color: 'text-accent-red',   label: 'Offline' },
};

const WS_DOT_COLOR: Record<WsStatus, string> = {
  connected: 'bg-accent-green shadow-[0_0_6px_#22c55e]',
  connecting:'bg-accent-yellow shadow-[0_0_6px_#eab308]',
  offline:   'bg-accent-red   shadow-[0_0_6px_#dc2626]',
};

// #28 — NAV_TABS with full ARIA support
const NAV_TABS: { id: ViewId; label: string }[] = [
  { id: 'chat',      label: 'Chat'      },
  { id: 'analytics', label: 'Analytics' },
  { id: 'memory',    label: 'Memory'    },
  { id: 'branch',    label: 'Branch'    },
  { id: 'plugins',   label: 'Plugins'   },
  { id: 'ab-test',   label: 'A/B Test'  },
];

interface StatPillProps {
  label: string;
  value: string | number;
  color: string;
}

function StatPill({ label, value, color }: StatPillProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-xs font-bold ${color}`}>{value}</span>
      <span className="text-[11px] text-text-faint">{label}</span>
    </div>
  );
}

export function Header({ wsStatus, stats, costs, view, onViewChange, theme = 'dark', onToggleTheme, onVoice }: HeaderProps) {
  const { color: dotColor, label: wsLabel } = WS_STATUS_CONFIG[wsStatus];

  // #28 — keyboard handler for arrow-key nav between tabs
  const handleTabKeyDown = (e: React.KeyboardEvent, currentIdx: number) => {
    let nextIdx = currentIdx;
    if (e.key === 'ArrowRight') nextIdx = (currentIdx + 1) % NAV_TABS.length;
    if (e.key === 'ArrowLeft')  nextIdx = (currentIdx - 1 + NAV_TABS.length) % NAV_TABS.length;
    if (nextIdx !== currentIdx) {
      e.preventDefault();
      onViewChange(NAV_TABS[nextIdx].id);
    }
  };

  return (
    <header className="flex items-center px-5 h-12 bg-surface-panel border-b border-border-dim flex-shrink-0 gap-6">

      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <span className="font-bold text-sm text-text-primary">Agent System</span>
        <span className="text-[11px] text-border-strong hidden sm:block">Claude · Gemini · Ollama</span>
      </div>

      <div className="w-px h-5 bg-border-dim" />

      {/* #28 — Nav tabs with full ARIA */}
      <nav role="tablist" aria-label="Main navigation" className="flex items-center gap-1">
        {NAV_TABS.map((tab, idx) => {
          const isActive = view === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => onViewChange(tab.id)}
              onKeyDown={(e) => handleTabKeyDown(e, idx)}
              className={`px-2.5 py-1 rounded-lg text-xs transition-all outline-none
                focus-visible:ring-2 focus-visible:ring-accent-blue
                ${isActive
                  ? 'bg-surface-active border border-border-strong text-text-primary font-semibold'
                  : 'border border-transparent text-text-muted hover:text-text-secondary'
                }`}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div className="w-px h-5 bg-border-dim" />

      {/* Stats */}
      <div className="flex items-center gap-4">
        <StatPill label="active"    value={stats.active}    color="text-accent-orange" />
        <StatPill label="done"      value={stats.completed} color="text-accent-green"  />
        <StatPill label="total"     value={stats.total}     color="text-accent-blue-light" />
        {costs?.total_cost_usd !== undefined && (
          <StatPill label="cost" value={`$${costs.total_cost_usd.toFixed(4)}`} color="text-accent-purple" />
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Cmd+K hint */}
      <div className="text-[10px] text-border-strong border border-border-base rounded px-1.5 py-0.5 hidden md:block">
        ⌘K
      </div>

      {/* Voice mode */}
      {onVoice && (
        <button
          onClick={onVoice}
          title="Voice conversation"
          aria-label="Voice conversation"
          className="border border-border-strong rounded-md text-text-muted hover:text-text-secondary px-2 py-1 text-sm transition-colors"
        >
          mic
        </button>
      )}

      {/* Theme toggle */}
      {onToggleTheme && (
        <button
          onClick={onToggleTheme}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          className="border border-border-strong rounded-md text-text-muted hover:text-text-secondary px-2 py-1 text-sm transition-colors"
        >
          {theme === 'dark' ? '☀' : '☽'}
        </button>
      )}

      {/* WS status */}
      <div className="flex items-center gap-1.5">
        <div className={`w-[7px] h-[7px] rounded-full ${WS_DOT_COLOR[wsStatus]}`} />
        <span className={`text-[11px] ${dotColor}`}>{wsLabel}</span>
      </div>
    </header>
  );
}

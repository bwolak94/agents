import type { AgentConfig } from '@/types/agent';

export const AGENT_CFG: Record<string, AgentConfig> = {
  code_agent: { icon: '👾', color: '#a855f7', bg: '#1e0a2e', zone: 'code', label: 'Code Agent' },
  research_agent: {
    icon: '🔭',
    color: '#3b82f6',
    bg: '#0a0e2e',
    zone: 'research',
    label: 'Research Agent',
  },
  learn_agent: { icon: '📖', color: '#eab308', bg: '#1a1500', zone: 'learn', label: 'Learn Agent' },
  file_agent: { icon: '🗂', color: '#22c55e', bg: '#001a0e', zone: 'files', label: 'File Agent' },
  general_agent: {
    icon: '🤖',
    color: '#94a3b8',
    bg: '#0f1117',
    zone: 'general',
    label: 'General Agent',
  },
};

export const DEFAULT_AGENT_CFG: AgentConfig = AGENT_CFG.general_agent;

export const MODEL_COLORS: Record<string, string> = {
  claude: '#c084fc',
  'claude-haiku': '#a855f7',
  gemini: '#60a5fa',
  'ollama/llama3': '#4ade80',
  'ollama/mistral': '#4ade80',
  'ollama/phi3': '#4ade80',
};

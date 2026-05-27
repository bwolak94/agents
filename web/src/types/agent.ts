export type AgentStatus = 'idle' | 'routing' | 'thinking' | 'using_tool' | 'done' | 'fading';

export interface AgentConfig {
  icon: string;
  color: string;
  bg: string;
  zone: string;
  label: string;
}

export interface Agent {
  id: string;
  type: string;
  model?: string;
  task?: string;
  status: AgentStatus;
  tools?: string[];
  tool?: string;
  startedAt?: number;
}

export type AgentMap = Record<string, Agent>;

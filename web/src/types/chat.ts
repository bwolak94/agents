export interface ChatMessage {
  role: 'user' | 'assistant' | 'error';
  content: string;
  model?: string;
  agent?: string;
  tools?: string[];
  reasoning?: string;
  ts?: string;          // ISO timestamp (#23)
}

export interface Stats {
  active: number;
  completed: number;
  total: number;
  routing: number;
  completedFlash: boolean;
}

export interface Costs {
  total_cost_usd: number;
  cache_read_tokens?: number;
}

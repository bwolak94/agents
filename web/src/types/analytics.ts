export interface AnalyticsTotals {
  total_requests: number;
  total_cost_usd: number;
  avg_duration_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

export interface AgentStat {
  agent: string;
  count: number;
  cost_usd: number;
}

export interface ModelStat {
  model: string;
  count: number;
  cost_usd: number;
}

export interface DailyStat {
  date: string;
  count: number;
  cost_usd: number;
}

export interface AnalyticsSummary {
  totals: AnalyticsTotals;
  by_agent: AgentStat[];
  by_model: ModelStat[];
  daily: DailyStat[];
}

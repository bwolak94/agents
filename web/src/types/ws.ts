export interface WsRoutingEvent {
  type: 'routing';
  agent_id: string;
  task?: string;
}

export interface WsAgentStartEvent {
  type: 'agent_start';
  agent_id: string;
  agent_type: string;
  model?: string;
  task?: string;
  tools?: string[];
}

export interface WsAgentThinkingEvent {
  type: 'agent_thinking';
  agent_id: string;
}

export interface WsAgentToolsEvent {
  type: 'agent_tools';
  agent_id: string;
  tools?: string[];
}

export interface WsAgentDoneEvent {
  type: 'agent_done';
  agent_id: string;
  duration_ms?: number;
}

export interface WsPingEvent {
  type: 'ping';
}

export type WsEvent =
  | WsRoutingEvent
  | WsAgentStartEvent
  | WsAgentThinkingEvent
  | WsAgentToolsEvent
  | WsAgentDoneEvent
  | WsPingEvent;

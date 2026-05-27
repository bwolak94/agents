export interface AppEvent {
  id: number;
  time: string;
  type: string;
  agent_id?: string;
  detail?: string;
}

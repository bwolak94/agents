export interface Zone {
  id: string;
  label: string;
  icon: string;
  color: string;
  bg: string;
  col: string | number;
  row: number;
}

export const ZONES: Zone[] = [
  { id: 'dispatch', label: 'DISPATCH', icon: '🏰', color: '#dc2626', bg: '#1a0000', col: '1 / 4', row: 1 },
  { id: 'code', label: 'CODE LAB', icon: '💻', color: '#a855f7', bg: '#1e0a2e', col: 1, row: 2 },
  { id: 'research', label: 'RESEARCH', icon: '🔭', color: '#3b82f6', bg: '#0a0e2e', col: 2, row: 2 },
  { id: 'learn', label: 'LIBRARY', icon: '📖', color: '#eab308', bg: '#1a1500', col: 3, row: 2 },
  { id: 'files', label: 'ARCHIVE', icon: '🗂', color: '#22c55e', bg: '#001a0e', col: 1, row: 3 },
  { id: 'general', label: 'GENERAL HQ', icon: '🤖', color: '#94a3b8', bg: '#0f1117', col: '2 / 4', row: 3 },
];

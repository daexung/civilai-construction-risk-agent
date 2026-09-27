export type ChoiceValue = string | boolean;

export interface QuestionHint {
  value: string;
  matched: string;
}

export interface DecisionRow {
  적용기준?: string;
  [key: string]: unknown;
}

export interface AgentQuestion {
  name: string;
  ask: string;
  choices?: ChoiceValue[] | null;
  hint?: QuestionHint | null;
  default?: string | null;
  decision_table?: Record<string, DecisionRow> | null;
  reason?: string | null;
}

export interface WorkInfo {
  spec_id: string;
  section_no: string;
  title: string;
  confirmed: boolean;
}

export interface InputRow {
  name: string;
  label: string;
  value: ChoiceValue;
  source: string;
}

export interface EvidenceItem {
  section_no: string;
  section: string;
  page: number;
  table_id?: string | null;
  snippet: string;
}

export interface SearchInfo {
  method: string;
  api_calls: number;
  warnings: string[];
}

export interface ResultLine {
  kind: 'labor' | 'equipment';
  name: string;
  value: string;
  unit: string;
  crew: string | null;
  rules: string[];
  source: string;
}

export interface UnitLine {
  kind: 'labor' | 'equipment';
  name: string;
  unit: string;
  exact: string;
  applied: string;
  places: number;
  formula: string;
  rule: string;
  source: string;
}

export interface ComputedResult {
  daily_volume: { value: string; unit: string; formula: string; sources: string[] };
  work_days: { value: string; formula: string };
  lines: ResultLine[];
  unit_lines: UnitLine[];
  unit_basis: { per: string; daily_output: string; places: number; adjustable_note: string };
  not_calculated: { item: string; source: string }[];
  review_status: string;
}

export interface BlockedResult {
  reason: string;
  source: string;
  input: string;
}

export type ChatStatus = 'OUT_OF_SCOPE' | 'EVIDENCE_ONLY' | 'MISSING_INFO' | 'COMPUTED' | 'BLOCKED' | 'ERROR';

export interface ChatResponse {
  thread_id: string;
  status: ChatStatus;
  message: string;
  work: WorkInfo | null;
  questions: AgentQuestion[];
  inputs: InputRow[];
  evidence: EvidenceItem[];
  result: ComputedResult | BlockedResult | null;
  search: SearchInfo;
}

export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  response?: ChatResponse;
}

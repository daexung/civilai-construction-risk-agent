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

export type ChatStatus = 'OUT_OF_SCOPE' | 'EVIDENCE_ONLY' | 'MISSING_INFO' | 'READY';

export interface ChatResponse {
  thread_id: string;
  status: ChatStatus;
  message: string;
  work: WorkInfo | null;
  questions: AgentQuestion[];
  inputs: InputRow[];
  evidence: EvidenceItem[];
  search: SearchInfo;
}

export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  response?: ChatResponse;
}

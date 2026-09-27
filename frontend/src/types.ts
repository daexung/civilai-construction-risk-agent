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
  citations: Citation[];
}

export interface Citation {
  code: string;
  division: string | null;
  section_no: string;
  section_title: string;
  section: string;
  subsection: string | null;
  item: string;
  row: string | null;
  column: string | null;
  value: string | null;
  pdf_page: number;
  printed_page: number | null;
  quote: string | null;
  internal_id: string;
  label: string;
  image_url?: string;
  reason?: string;
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
  citations: Citation[];
}

export interface ComputedResult {
  daily_volume: { value: string; unit: string; formula: string; sources: string[]; citations: Citation[] };
  work_days: { value: string; formula: string };
  lines: ResultLine[];
  unit_lines: UnitLine[];
  unit_basis: { per: string; daily_output: string; places: number; adjustable_note: string };
  not_calculated: { item: string; source: string; citations: Citation[] }[];
  review_status: string;
}

export interface PricedLine {
  kind: 'labor' | 'equipment' | 'rate_cost';
  category: string;
  name: string;
  unit?: string;
  quantity?: string;
  rate_code?: string | null;
  unit_price?: string | null;
  base?: string;
  rate?: string;
  amount_exact: string | null;
  amount: string | null;
  reason: string | null;
  citations: Citation[];
}

export interface PricedResult {
  status: 'OK' | 'PARTIAL';
  partial: boolean;
  rate_version: {
    id: string;
    title: string;
    publisher: string;
    effective_from: string;
    effective_to: string | null;
    source_file: string;
    unit: string;
  } | null;
  lines: PricedLine[];
  cost_lines: PricedLine[];
  labor_subtotal: string | null;
  subtotals: Record<'재료비' | '노무비' | '경비', string | null>;
  total_exact: string | null;
  total: string | null;
  total_citations: Citation[];
  unpriced: { name: string; reason: string; category: string | null; citations: Citation[] }[];
}

export interface BlockedResult {
  reason: string;
  source: string;
  input: string;
  citations: Citation[];
}

export type ChatStatus = 'OUT_OF_SCOPE' | 'EVIDENCE_ONLY' | 'MISSING_INFO' | 'COMPUTED' | 'BLOCKED' | 'ERROR' | 'OK' | 'PARTIAL';

export interface ChatResponse {
  thread_id: string;
  status: ChatStatus;
  message: string;
  work: WorkInfo | null;
  questions: AgentQuestion[];
  inputs: InputRow[];
  evidence: EvidenceItem[];
  result: ComputedResult | BlockedResult | null;
  priced: PricedResult | null;
  basis_date: string;
  search: SearchInfo;
}

export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  response?: ChatResponse;
}

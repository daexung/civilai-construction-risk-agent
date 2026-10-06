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
  labels?: Record<string, string> | null;
  hint?: QuestionHint | null;
  default?: string | null;
  decision_table?: Record<string, DecisionRow> | null;
  reason?: string | null;
  citations?: Citation[];
}

export interface WorkInfo {
  spec_id: string;
  section_no: string | null;
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
  raw_warnings?: string[];
}

export interface ResultLine {
  kind: 'labor' | 'equipment' | 'material';
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
  pdf_page: number | null;
  printed_page: number | null;
  quote: string | null;
  internal_id: string;
  label: string;
  image_url?: string;
  reason?: string;
}

export interface UnitLine {
  kind: 'labor' | 'equipment' | 'material';
  name: string;
  unit: string;
  exact: string;
  applied: string;
  places: number;
  formula: string;
  rule: string;
  source: string;
  citations: Citation[];
  adjustments?: { 종류: string; 값: string; '원문 인용': string; citations: Citation[] }[];
}

export interface ComputedResult {
  daily_volume: { value: string; unit: string; formula: string; sources: string[]; citations: Citation[] } | null;
  work_days: { value: string; formula: string } | null;
  lines: ResultLine[];
  unit_lines: UnitLine[];
  unit_basis: { per: string; daily_output: string; places: number; adjustable_note: string };
  not_calculated: { item: string; source: string; citations: Citation[] }[];
  review_status: string;
  adjustment_memos?: string[];
}

export interface PricedLine {
  kind: 'labor' | 'equipment' | 'material' | 'rate_cost' | 'equipment_component' | 'supply_component';
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
  machine_code?: string;
  machine_spec?: string;
  fuel_l_per_hr?: string;
  fuel_l_per_unit?: string;
  misc_pct_of_fuel?: number;
  status?: '산정' | '제외' | '미산정';
  spec?: string;
  allowance?: string;
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
  equipment_rate_version: {
    version: string;
    title: string;
    publisher: string;
    published: string;
    effective_from: string;
    effective_to: string;
    source_file: string;
    effective_period_basis: string;
  } | null;
  lines: PricedLine[];
  equipment_lines?: PricedLine[];
  cost_lines: PricedLine[];
  supply_lines?: PricedLine[];
  labor_subtotal: string | null;
  subtotals: Record<'재료비' | '노무비' | '경비', string | null>;
  total_exact: string | null;
  total: string | null;
  reference_amounts?: {
    volume: string;
    subtotals: Record<'재료비' | '노무비' | '경비', string | null>;
    total: string | null;
  } | null;
  total_citations: Citation[];
  unpriced: { name: string; reason: string; category: string | null; citations: Citation[] }[];
  excluded?: { name: string; reason: string; category: string | null; citations: Citation[] }[];
}

export interface BlockedResult {
  reason: string;
  source: string;
  input: string;
  citations: Citation[];
}

export interface ConditionField {
  name: 'work_category' | 'duration' | 'contractor_type' | 'project_scale';
  label: string;
  value: string;
  source: string;
  type: string;
  choices: string[];
  help: Record<string, string>;
  default: string;
  groups?: Record<string, string[]>;
  group?: string;
}

export interface StatementRow {
  name: string;
  category: string | null;
  basis: string;
  amount: number | null;
  status: '산정' | '제외' | '미산정';
  reason: string | null;
  note: string | null;
  kind: 'item' | 'subtotal' | 'total';
  final: boolean;
}

export interface BillRow {
  name: string;
  spec: string;
  unit: string;
  quantity: string;
  unit_price: Record<'재료비' | '노무비' | '경비', string | null>;
  amount: Record<'재료비' | '노무비' | '경비', string | null>;
  total: string | null;
  partial: boolean;
}

export interface RateRow {
  kind: string;
  name: string;
  unit: string;
  price: string | null;
  source: string;
}

export interface ResultTables {
  statement_rows: StatementRow[];
  bill: BillRow | null;
  rate_rows: RateRow[];
}

export interface StatementResult {
  basis_notes?: string[];
}

export type ChatStatus = 'ANSWERED' | 'OUT_OF_SCOPE' | 'EVIDENCE_ONLY' | 'MISSING_INFO' | 'COMPUTED' | 'BLOCKED' | 'ERROR' | 'OK' | 'PARTIAL';

export interface UsageStatus {
  limit: number;
  used: number;
  remaining: number;
  service_limit: number;
  service_remaining: number;
  resets_at: string;
  timezone: string;
}

export interface ChatResponse {
  usage?: UsageStatus;
  thread_id: string;
  route?: 'estimate' | 'qa' | 'out_of_scope' | null;
  status: ChatStatus;
  message: string;
  work: WorkInfo | null;
  questions: AgentQuestion[];
  inputs: InputRow[];
  evidence: EvidenceItem[];
  result: ComputedResult | BlockedResult | null;
  priced: PricedResult | null;
  statement: StatementResult | null;
  conditions: ConditionField[];
  tables: ResultTables;
  qa?: { not_found: boolean; not_found_kind?: 'section_not_found' | 'section_found_value_missing'; conclusion: string; explanation: string;
    comparisons: { section: string; summary: string; citation_ids?: string[] }[];
    citations: (Citation & { chunk_id: string; quote_match?: 'normalized' | 'fuzzy' })[] } | null;
  llm_info?: { model: string; elapsed_ms: number; error: string | null } | null;
  answer: string | null;
  answer_source: 'llm' | 'template' | 'fixed' | null;
  basis_date: string;
  search: SearchInfo;
  timing?: { route_ms: number; retrieve_ms: number; compute_ms: number; llm_ms: number; total_ms: number };
}

export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  text?: string;
  response?: ChatResponse;
  elapsedMs?: number;
  sentAtMs?: number;
  receivedAtMs?: number;
}

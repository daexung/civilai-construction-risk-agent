// 5단계 로컬 시험 전용 API. 기본 꺼짐(REACT_APP_LOCAL_TRIAL=on일 때만 화면에서 사용). 인증·사용량·원격 저장을 쓰지 않는다.
export type TrialStatus = 'supported' | 'needs_confirmation' | 'not_found' | 'error';

export type TrialAnswerStatus = 'confirmed' | 'condition_unconfirmed' | 'source_check_needed' | 'needs_confirmation' | 'not_found' | 'error';

export interface TrialLine { n: number; text: string; display?: string; selected: boolean; cited?: boolean; page?: number | null; }
export interface TrialCondition { number: number; ok: boolean; where: string; cell?: string | null; }
export interface TrialValueClaim {
  value: string; unit: string; location: string; declared: boolean; row_label?: string | null; column_name?: string | null; unit_basis?: string | null;
  alignment?: string; conditions?: TrialCondition[]; matches_question_conditions?: boolean;
}
export interface TrialCitation { location: string; chunk_id: string; line: number; kind: string; quote: string; display: string; page?: number | null; unit_basis?: string | null; row_label?: string | null; }
export interface TrialSource {
  id: string; role: string; division?: string; section_no?: string; section_title?: string; kind: string;
  frame: string[]; lines: TrialLine[]; pdf_page?: number | null; printed_page?: number | null; flags: string[]; note?: string | null; cited?: boolean;
  shared_legend?: { n: number; text: string }[];
}
export interface TrialResponse {
  request_id: string; status: TrialStatus; status_label: string; answer: string | null;
  search_status?: TrialStatus; answer_status?: TrialAnswerStatus; answer_status_label?: string; answer_status_reason?: { code: string; text: string };
  citations?: TrialCitation[]; value_claims?: TrialValueClaim[];
  reasons: { code: string; text: string }[]; confirmations: { code: string; text: string }[];
  sources: TrialSource[]; related?: TrialSource[]; review_material: TrialSource[]; diagnostic: { id: string; label: string; why: string; in_context: boolean }[];
  alternatives: { division: string; number: string; title: string; pdf_page?: number | null }[];
  generation: { source: string; model?: string; error?: string; code?: string; state?: string; latency_ms?: number; truncated?: boolean; attempts?: number;
    usage?: { prompt_tokens: number; output_tokens: number; cost_usd: number } };
  list?: { scope?: string; included: { section_id: string; division: string; number: string; title: string; pdf_page?: number | null }[]; uncertain_n: number; note: string } | null;
  versions?: { release_id: string; chunk_set_id: string; policy: string; select_verified_code_sha256: string };
  timing_ms?: { search_select: number; total: number } | number;
  applicability?: string;
}

const BASE = process.env.REACT_APP_API_URL ?? '';

export const trialPageUrl = (page: number) => `${BASE}/api/local-trial/page/${page}.png`;

export async function askTrial(message: string): Promise<TrialResponse> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/local-trial/ask`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) });
  } catch { throw new Error('NETWORK_ERROR'); }
  if (!res.ok) throw new Error(res.status === 404 ? 'TRIAL_DISABLED' : 'SERVER_ERROR');
  return res.json();
}

export async function trialHealth(): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/local-trial/health`);
  if (!res.ok) throw new Error('TRIAL_DISABLED');
  return res.json();
}

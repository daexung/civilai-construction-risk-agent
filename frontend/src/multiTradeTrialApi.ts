// The trial is strictly local even when the production chat API is configured.
// Use same-origin dev proxy requests and fail closed on any non-loopback page.
const BASE = '';
const PREFIX = '/api/item-labor';
const REQUEST_TIMEOUT_MS = 12000;
const DOWNLOAD_TIMEOUT_MS = 30000;

function assertLocalOrigin() {
  if (typeof window === 'undefined') return;
  const host = window.location.hostname.toLowerCase();
  if (!['localhost', '127.0.0.1', '::1'].includes(host)) {
    throw new Error('이 시험 화면은 로컬 브라우저에서만 사용할 수 있습니다.');
  }
}

export interface TrialAnalysis {
  scope_spans: Array<Record<string, any>>;
  work_items: Array<Record<string, any>>;
  questions?: string[];
  limitations?: string[];
}
export interface TrialItem {
  item_id: string;
  task: string;
  request_text?: string;
  source_spans?: Array<Record<string, any>>;
  status: string;
  scope_confirmed: boolean;
  search_status?: string;
  search_info?: Record<string, any>;
  search_message?: string;
  candidates?: Array<Record<string, any>>;
  selected_specification?: { id: string; section_no: string; title: string } | null;
  quantity?: { value: string | number; unit?: string } | null;
  conditions?: Record<string, any>;
  input_revision?: number;
  evidence?: Record<string, any>;
  not_calculated_scope?: Array<Record<string, any>>;
  questions: Array<Record<string, any>>;
  labor?: Record<string, any> | null;
}
export interface TrialState {
  trial_id: string;
  status: string;
  scope_confirmation?: Record<string, any> | null;
  items: TrialItem[];
  excluded_scope?: Array<Record<string, any>>;
  unconfirmed_scope?: Array<Record<string, any>>;
  not_calculated_scope?: Array<Record<string, any>>;
}
export interface AnalyzeResponse {
  trial_id: string;
  owner_token: string;
  status: string;
  analysis: TrialAnalysis;
}
export interface EstimateResponse {
  status: string;
  aggregate?: Record<string, any> | null;
  partial_estimate?: Record<string, any> | null;
  statement?: Record<string, any> | null;
  common_questions?: Array<Record<string, any>>;
  common_conditions?: Record<string, any>;
  basis_date?: string;
  items?: Array<Record<string, any>>;
  tables?: Record<string, any>;
}

export function health(): Promise<Record<string, any>> {
  return request('/health', null, undefined, 'GET');
}

async function request<T>(path: string, owner: string | null, body?: unknown, method = 'POST'): Promise<T> {
  assertLocalOrigin();
  const headers = new Headers();
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  if (owner) headers.set('X-Trial-Owner', owner);
  let response: Response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    response = await fetch(`${BASE}${PREFIX}${path}`, {
      method, headers, signal: controller.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (exc) {
    if ((exc as Error).name === 'AbortError') throw new Error('로컬 시험 API 응답 시간이 초과되었습니다. 서버 상태를 확인해 주세요.');
    throw new Error('로컬 시험 API에 연결할 수 없습니다. 로컬 서버와 proxy 설정을 확인해 주세요.');
  } finally { window.clearTimeout(timeout); }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message;
    throw new Error(message || `로컬 시험 API 오류 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function analyze(text: string): Promise<AnalyzeResponse> {
  return request('/analyze', null, { text });
}
export function confirmScope(trialId: string, owner: string, decisions: Array<Record<string, string>>): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}/confirm`, owner, { decisions });
}
export function readTrial(trialId: string, owner: string): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}`, owner, undefined, 'GET');
}
export function searchItem(trialId: string, itemId: string, owner: string): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}/items/${encodeURIComponent(itemId)}/search`, owner);
}
export function answerItem(trialId: string, itemId: string, owner: string, answer: Record<string, unknown>): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}/items/${encodeURIComponent(itemId)}/answer`, owner, answer);
}
export function editItem(trialId: string, itemId: string, owner: string, edit: Record<string, unknown>): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}/items/${encodeURIComponent(itemId)}/edit`, owner, edit);
}
export function confirmEdit(trialId: string, itemId: string, owner: string, inputRevision: number): Promise<TrialState> {
  return request(`/${encodeURIComponent(trialId)}/items/${encodeURIComponent(itemId)}/confirm-edit`, owner,
    { input_revision: inputRevision, confirmed: true });
}
export function invalidateTrial(trialId: string, owner: string): Promise<{ invalidated: boolean }> {
  return request(`/${encodeURIComponent(trialId)}/invalidate`, owner);
}
export function estimate(trialId: string, owner: string, basisDate: string): Promise<EstimateResponse> {
  return request(`/${encodeURIComponent(trialId)}/estimate`, owner, { basis_date: basisDate, common_conditions: {} });
}
export function answerCommon(trialId: string, owner: string, field: string, value: unknown): Promise<EstimateResponse> {
  return request(`/${encodeURIComponent(trialId)}/common-answer`, owner, { field, value });
}
export async function downloadEstimate(trialId: string, owner: string): Promise<Blob> {
  assertLocalOrigin();
  const headers = new Headers({ 'X-Trial-Owner': owner });
  let response: Response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);
  try {
    response = await fetch(`${BASE}${PREFIX}/${encodeURIComponent(trialId)}/estimate.xlsx`, { headers, signal: controller.signal });
  } catch (exc) {
    if ((exc as Error).name === 'AbortError') throw new Error('엑셀 다운로드 시간이 초과되었습니다. 다시 시도해 주세요.');
    throw new Error('엑셀 파일을 가져오지 못했습니다.');
  } finally { window.clearTimeout(timeout); }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : '현재 상태에서는 엑셀을 내려받을 수 없습니다.');
  }
  return response.blob();
}

import { ChatResponse, ChatTurn, ChoiceValue, UsageStatus } from './types';
import { authClient } from './auth';
import { v4 as uuidv4 } from 'uuid';
import { trackEvent } from './analytics';

const API_BASE = process.env.REACT_APP_API_URL ?? '';
const guestSession = (() => {
  const key = 'poomsemi-guest-session-v1';
  try {
    const existing = sessionStorage.getItem(key);
    if (existing && /^[a-f0-9-]{72}$/i.test(existing)) return existing;
    const value = uuidv4() + uuidv4();
    sessionStorage.setItem(key, value);
    return value;
  } catch { return uuidv4() + uuidv4(); }
})();

export class UsageError extends Error {
  constructor(message: string, public usage?: UsageStatus) { super(message); }
}

export interface ChatRequestBody {
  thread_id?: string | null;
  message?: string;
  answers?: Record<string, ChoiceValue>;
  basis_date?: string;
  conditions?: Record<string, string>;
  conversation_id?: string;
  request_id?: string;
  user_label?: string;
}

export const exportUrl = (threadId: string) => `${API_BASE}/api/export/${threadId}.xlsx`;

async function request(path: string, init: RequestInit = {}, member = true, expectedUserId?: string): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Guest-Session', guestSession);
  if (member) {
    const session = await authClient?.auth.getSession();
    if (!session?.data.session?.access_token) throw new Error('AUTH_REQUIRED');
    if (expectedUserId && session.data.session.user.id !== expectedUserId) throw new Error('AUTH_REQUIRED');
    headers.set('Authorization', `Bearer ${session.data.session.access_token}`);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new Error('NETWORK_ERROR');
  }
  if (!res.ok) {
    if (res.status === 429) {
      const detail = (await res.json().catch(() => ({}))).detail;
      throw new UsageError(detail?.message ?? '요청이 많습니다. 잠시 후 다시 시도해 주세요.', detail?.usage);
    }
    throw new Error(res.status === 401 ? 'AUTH_REQUIRED' : res.status === 404 ? 'NOT_FOUND' : res.status >= 500 ? 'SERVER_ERROR' : 'REQUEST_ERROR');
  }
  return res;
}

export async function sendChat(body: ChatRequestBody): Promise<ChatResponse> {
  return (await request('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }, !!body.conversation_id)).json();
}

export async function getUsage(member: boolean): Promise<UsageStatus> {
  return (await request('/api/usage', {}, member)).json();
}

export async function sendFeedback(body: { request_id: string; category: 'bug' | 'suggestion' | 'other'; message: string }, expectedUserId?: string): Promise<{ id: string }> {
  return (await request('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }, !!expectedUserId, expectedUserId)).json();
}

export async function sendAnswerFeedback(body: { thread_id: string; answer_id: string; rating: 'good' | 'bad'; reason?: string; comment?: string }, expectedUserId?: string): Promise<{ rating: 'good' | 'bad' }> {
  return (await request('/api/answer-feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }, !!expectedUserId, expectedUserId)).json();
}

export async function downloadEstimate(threadId: string): Promise<void> {
  const session = await authClient?.auth.getSession();
  const member = !!session?.data.session && threadId.includes('-');
  const res = await request(`/api/export/${threadId}.xlsx`, {}, member);
  const href = URL.createObjectURL(await res.blob());
  const anchor = document.createElement('a');
  let filename = '품셈이_견적서.xlsx';
  const disposition = res.headers?.get('Content-Disposition') ?? '';
  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  const quoted = /filename\s*=\s*"([^"]+)"/i.exec(disposition);
  try {
    const proposed = encoded ? decodeURIComponent(encoded[1].trim()) : quoted?.[1];
    if (proposed?.toLowerCase().endsWith('.xlsx')) {
      filename = Array.from(proposed.replace(/[\\/:*?"<>|]/g, '_'))
        .map(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127 ? '_' : character)
        .join('').slice(0, 180);
    }
  } catch { /* Keep the fallback if the server filename is malformed. */ }
  anchor.href = href; anchor.download = filename; anchor.click();
  trackEvent('estimate_downloaded', { member });
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export interface SavedConversation { id: string; title: string; }
export async function beginAccountDeletion(expectedUserId: string): Promise<{ challenge_id: string }> {
  return (await request('/api/account/deletion-challenge', { method: 'POST' }, true, expectedUserId)).json();
}
export async function deleteAccount(challengeId: string, expectedUserId: string): Promise<void> {
  await request('/api/account', { method: 'DELETE', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ challenge_id: challengeId, confirmation: '탈퇴' }) }, true, expectedUserId);
}
export async function listConversations(): Promise<SavedConversation[]> {
  return (await request('/api/conversations')).json();
}
export async function readConversation(id: string): Promise<ChatTurn[]> {
  const result = await (await request(`/api/conversations/${id}`)).json();
  return result.messages.map((row: any) => row.role === 'user'
    ? { id: row.id, role: 'user', text: row.content, sentAtMs: Date.parse(row.created_at) }
    : { id: row.id, role: 'assistant', response: row.payload, receivedAtMs: Date.parse(row.created_at) });
}

export async function deleteConversation(id: string, saved: boolean, threadId: string | null): Promise<void> {
  if (!saved && !threadId) return;
  await request(saved ? `/api/conversations/${id}` : `/api/guest/conversations/${threadId}`,
    { method: 'DELETE' }, saved);
}

export async function renameConversation(id: string, title: string, expectedUserId: string): Promise<void> {
  await request(`/api/conversations/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }) }, true, expectedUserId);
}

export async function importGuestConversation(threadId: string, conversationId: string, expectedUserId?: string): Promise<string> {
  const result = await (await request('/api/conversations/import-guest', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ thread_id: threadId, conversation_id: conversationId }) }, true, expectedUserId)).json();
  return result.id;
}

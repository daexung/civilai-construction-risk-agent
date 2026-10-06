import { ChatResponse, ChatTurn, ChoiceValue } from './types';
import { authClient } from './auth';
import { v4 as uuidv4 } from 'uuid';

const API_BASE = process.env.REACT_APP_API_URL ?? '';
const guestSession = uuidv4() + uuidv4();

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

async function request(path: string, init: RequestInit = {}, member = true): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-Guest-Session', guestSession);
  if (member) {
    const session = await authClient?.auth.getSession();
    if (!session?.data.session?.access_token) throw new Error('AUTH_REQUIRED');
    headers.set('Authorization', `Bearer ${session.data.session.access_token}`);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new Error('NETWORK_ERROR');
  }
  if (!res.ok) {
    throw new Error(res.status === 401 ? 'AUTH_REQUIRED' : res.status === 404 ? 'NOT_FOUND' : res.status >= 500 ? 'SERVER_ERROR' : 'REQUEST_ERROR');
  }
  return res;
}

export async function sendChat(body: ChatRequestBody): Promise<ChatResponse> {
  return (await request('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }, !!body.conversation_id)).json();
}

export async function downloadEstimate(threadId: string): Promise<void> {
  const session = await authClient?.auth.getSession();
  const member = !!session?.data.session && threadId.includes('-');
  const res = await request(`/api/export/${threadId}.xlsx`, {}, member);
  const href = URL.createObjectURL(await res.blob());
  const anchor = document.createElement('a');
  anchor.href = href; anchor.download = '품셈이_견적서.xlsx'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export interface SavedConversation { id: string; title: string; }
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

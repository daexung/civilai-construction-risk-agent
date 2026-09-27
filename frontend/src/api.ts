import { AuthResponse, Project, ProjectCreateRequest, ProjectMember, ProjectRole, Conversation, Message } from './types';
import { MOCK_MODE, mockSendMessage, mockFetchMembers, mockAddMember, mockRemoveMember } from './mockData';

const BASE = process.env.REACT_APP_API_BASE ?? '';

// ── 401 핸들러 (토큰 만료 시 자동 로그아웃) ──────────────────
let onUnauthorized: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function apiFetch(url: string, options?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, options);
  } catch {
    throw new Error('NETWORK_ERROR');
  }
  if (res.status === 401) { onUnauthorized?.(); throw new Error('UNAUTHORIZED'); }
  if (res.status === 503)  throw new Error('SERVICE_UNAVAILABLE');
  if (res.status >= 500)   throw new Error('SERVER_ERROR');
  return res;
}

function authHeader(): Record<string, string> {
  const token = localStorage.getItem('auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ══════════════════════════════
// Auth
// ══════════════════════════════
export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error('로그인에 실패했습니다');
  return res.json();
}

export async function fetchMe(): Promise<Omit<AuthResponse, 'token'>> {
  const res = await apiFetch(`${BASE}/auth/me`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchMe: ${res.status}`);
  return res.json();
}

// ══════════════════════════════
// Quick conversations (일반 대화)
// ══════════════════════════════
export async function fetchQuickConversations(): Promise<Conversation[]> {
  const res = await apiFetch(`${BASE}/conversations/quick`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchQuickConversations: ${res.status}`);
  return res.json();
}

export async function createQuickConversation(title = '새 대화'): Promise<Conversation> {
  const res = await apiFetch(`${BASE}/conversations/quick`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`createQuickConversation: ${res.status}`);
  return res.json();
}

// ══════════════════════════════
// Projects
// ══════════════════════════════
export async function fetchProjects(): Promise<Project[]> {
  const res = await apiFetch(`${BASE}/projects`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchProjects: ${res.status}`);
  return res.json();
}

export async function createProject(req: ProjectCreateRequest): Promise<Project> {
  const res = await apiFetch(`${BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`createProject: ${res.status}`);
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch(`${BASE}/projects/${projectId}`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

// ══════════════════════════════
// Project conversations
// ══════════════════════════════
export async function fetchConversations(projectId: string): Promise<Conversation[]> {
  const res = await apiFetch(`${BASE}/projects/${projectId}/conversations`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchConversations: ${res.status}`);
  return res.json();
}

export async function createConversation(projectId: string, title = '새 대화'): Promise<Conversation> {
  const res = await apiFetch(`${BASE}/projects/${projectId}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`createConversation: ${res.status}`);
  return res.json();
}

export async function renameConversation(convId: string, title: string): Promise<void> {
  if (MOCK_MODE) return;
  await apiFetch(`${BASE}/conversations/${convId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(convId: string): Promise<void> {
  if (MOCK_MODE) return;
  await apiFetch(`${BASE}/conversations/${convId}`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

// ══════════════════════════════
// Project members
// ══════════════════════════════
export async function fetchProjectMembers(projectId: string): Promise<ProjectMember[]> {
  if (MOCK_MODE) return mockFetchMembers(projectId);
  const res = await apiFetch(`${BASE}/projects/${projectId}/members`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchProjectMembers: ${res.status}`);
  return res.json();
}

export async function addProjectMember(projectId: string, email: string, role: ProjectRole): Promise<ProjectMember> {
  if (MOCK_MODE) return mockAddMember(projectId, email, role);
  const res = await apiFetch(`${BASE}/projects/${projectId}/members`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ email, role }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? '초대에 실패했습니다.');
  }
  return res.json();
}

export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
  if (MOCK_MODE) return mockRemoveMember(projectId, userId);
  await apiFetch(`${BASE}/projects/${projectId}/members/${userId}`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

// ══════════════════════════════
// Messages / Chat
// ══════════════════════════════
export async function fetchMessages(convId: string): Promise<Message[]> {
  const res = await apiFetch(`${BASE}/conversations/${convId}/messages`, { headers: authHeader() });
  if (!res.ok) throw new Error(`fetchMessages: ${res.status}`);
  const data = await res.json();
  return data.messages ?? data;
}

export async function sendConvMessage(convId: string, content: string, signal?: AbortSignal): Promise<Message> {
  if (MOCK_MODE) {
    return mockSendMessage(convId, content, signal);
  }
  const res = await apiFetch(`${BASE}/conversations/${convId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok) throw new Error(`sendConvMessage: ${res.status}`);
  return res.json();
}

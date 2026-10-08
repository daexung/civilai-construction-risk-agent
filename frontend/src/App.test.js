import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import App from './App';
import { sendChat, listConversations, readConversation, deleteConversation, renameConversation, importGuestConversation, getUsage, UsageError } from './api';
import { loginWithGoogle } from './auth';

jest.mock('./api', () => ({ sendChat: jest.fn(), downloadEstimate: jest.fn(), listConversations: jest.fn(), readConversation: jest.fn(), deleteConversation: jest.fn(), renameConversation: jest.fn(), importGuestConversation: jest.fn(), getUsage: jest.fn(), UsageError: class extends Error { constructor(message, usage) { super(message); this.usage = usage; } } }));
let mockAuthClient = null;
jest.mock('./auth', () => ({ get authClient() { return mockAuthClient; }, AuthCallback: () => null, loginWithGoogle: jest.fn() }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => {} }));

let root, container;
const response = (thread_id, message) => ({ thread_id, message, status: 'OUT_OF_SCOPE', work: null, tables: { bill: null, statement_rows: [] }, search: { warnings: [], raw_warnings: [] } });
beforeEach(async () => {
  mockAuthClient = null;
  getUsage.mockReset().mockResolvedValue({ limit: 5, used: 0, remaining: 5, service_limit: 500, service_remaining: 500, resets_at: new Date(Date.now() + 3600000).toISOString(), timezone: 'Asia/Seoul' });
  loginWithGoogle.mockReset();
  listConversations.mockReset().mockResolvedValue([]);
  readConversation.mockReset().mockResolvedValue([]);
  deleteConversation.mockReset().mockResolvedValue(undefined);
  renameConversation.mockReset().mockResolvedValue(undefined);
  importGuestConversation.mockReset().mockImplementation(async (_thread, id) => id);
  global.IS_REACT_ACT_ENVIRONMENT = true;
  Element.prototype.scrollIntoView = jest.fn();
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, '', '/chat');
  sendChat.mockReset();
  sendChat.mockImplementation(async body => response(body.thread_id ?? `thread-${body.message}`, `답변: ${body.message}`));
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<App />));
  const betaClose = document.querySelector('.beta-notice-close');
  if (betaClose) act(() => Simulate.click(betaClose));
});

test('shows remaining usage and disables sending when the server reports a daily limit', async () => {
  await act(async () => {});
  expect(container.querySelector('.centered-input-area .account-usage')).toBeNull();
  const exhausted = { limit: 5, used: 5, remaining: 0, service_limit: 500, service_remaining: 400, resets_at: new Date(Date.now() + 3600000).toISOString(), timezone: 'Asia/Seoul' };
  sendChat.mockRejectedValueOnce(new UsageError('오늘 5회를 모두 사용했습니다.', exhausted));
  await sendQuestion('마지막 질문');
  expect(container.querySelector('textarea').disabled).toBe(true);
  act(() => Simulate.click(container.querySelector('.chat-sidebar-action')));
  act(() => Simulate.click(document.querySelectorAll('.settings-body nav button')[1]));
  expect(document.querySelector('.settings-body .account-usage').textContent).toContain('0 / 5회');
});

test('refreshes exhausted usage at midnight and enables sending again', async () => {
  jest.useFakeTimers();
  try {
    const exhausted = { limit: 5, used: 5, remaining: 0, service_limit: 500, service_remaining: 400,
      resets_at: new Date(Date.now() + 1000).toISOString(), timezone: 'Asia/Seoul' };
    sendChat.mockRejectedValueOnce(new UsageError('오늘 한도 도달', exhausted));
    await sendQuestion('질문');
    expect(container.querySelector('textarea').disabled).toBe(true);
    await act(async () => { jest.advanceTimersByTime(1101); });
    expect(container.querySelector('textarea').disabled).toBe(false);
    expect(getUsage).toHaveBeenCalledTimes(2);
  } finally { jest.useRealTimers(); }
});

test('popup login preserves guest turns and logout clears the account view', async () => {
  await sendQuestion('진행 중인 견적');
  loginWithGoogle.mockResolvedValue({ id: 'A', email: 'a@example.com', user_metadata: { full_name: '홍길동' } });
  await act(async () => Simulate.click(container.querySelector('.chat-sidebar-login button')));
  expect(loginWithGoogle).not.toHaveBeenCalled();
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => Simulate.click(document.querySelector('.login-dialog-google')));
  expect(container.querySelector('.messages').textContent).toContain('진행 중인 견적');
  expect(container.querySelector('.chat-account-name').textContent).toBe('홍길동');
  expect(container.querySelector('.chat-sidebar-login')).toBeNull();
  expect(container.querySelector('.chat-sidebar').textContent).not.toContain('로그아웃');
  expect(localStorage.getItem('poomsemi-chat-history-v1')).toBeNull();
  expect(importGuestConversation).toHaveBeenCalledWith('thread-진행 중인 견적', expect.any(String), 'A');
  const migratedId = importGuestConversation.mock.calls[0][1];
  await sendQuestion('로그인 후 이어가기');
  expect(sendChat.mock.calls[1][0].conversation_id).toBe(migratedId);
  expect(sendChat.mock.calls[1][0].thread_id).toBe(migratedId);
  act(() => Simulate.click(container.querySelector('[aria-label="계정 메뉴 열기"]')));
  expect(document.querySelector('.settings-dialog')).toBeNull();
  expect(container.querySelector('.chat-account-menu').textContent).toContain('남은 사용량');
  expect(container.querySelector('.chat-account').getAttribute('aria-expanded')).toBe('true');
  expect(container.querySelector('.chat-account-chevron').classList.contains('is-open')).toBe(true);
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(container.querySelector('.chat-account-menu')).toBeNull();
  act(() => Simulate.click(container.querySelector('.chat-sidebar-action')));
  expect(document.querySelector('.settings-identity').textContent).toContain('a@example.com');
  await act(async () => Simulate.click(document.querySelector('.settings-logout')));
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(0);
  expect(container.querySelector('.chat-sidebar-login button').textContent).toBe('로그인');
});

test('guest settings switches sections and opens the login dialog from account', () => {
  act(() => Simulate.click(container.querySelector('.chat-sidebar-action')));
  expect(document.querySelector('.settings-body section').getAttribute('aria-label')).toBe('일반 설정');
  expect(document.querySelector('.settings-body section').textContent).toContain('한국어');
  act(() => Simulate.click(document.querySelectorAll('.settings-body nav button')[1]));
  expect(document.querySelector('.settings-body section').textContent).toContain('로그인하지 않은 상태');
  act(() => Simulate.click(document.querySelector('.settings-guest button')));
  expect(document.querySelector('.settings-dialog')).toBeNull();
  expect(document.querySelector('.login-dialog')).not.toBeNull();
  expect(loginWithGoogle).not.toHaveBeenCalled();
});

test('login dialog closes with Escape without closing the sidebar or starting OAuth', () => {
  const button = container.querySelector('.chat-sidebar-login button');
  button.focus();
  act(() => Simulate.click(button));
  expect(container.querySelector('.app').hasAttribute('inert')).toBe(true);
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(container.querySelector('.chat-sidebar')).not.toBeNull();
  expect(container.querySelector('.app').hasAttribute('inert')).toBe(false);
  expect(document.activeElement).toBe(button);
  expect(loginWithGoogle).not.toHaveBeenCalled();
});
afterEach(() => { act(() => root.unmount()); container.remove(); localStorage.clear(); });

test('resend and edit append requests in the same conversation without resuming pending conditions', async () => {
  await sendQuestion('자동문 3개소 설치 비용');
  const thread = sendChat.mock.results[0].value;
  const original = await thread;
  await act(async () => Simulate.click(container.querySelector('[aria-label="질문 다시 보내기"]')));
  expect(sendChat).toHaveBeenLastCalledWith(expect.objectContaining({ thread_id: original.thread_id, message: '자동문 3개소 설치 비용', restart: true }));
  expect(container.querySelectorAll('.user-bubble')).toHaveLength(2);
  act(() => Simulate.click(container.querySelector('[aria-label="질문 편집하기"]')));
  const editor = container.querySelector('[aria-label="질문 편집"]');
  expect(editor.value).toBe('자동문 3개소 설치 비용');
  act(() => Simulate.change(editor, { target: { value: '  자동문 5개소 설치 비용  ' } }));
  await act(async () => Simulate.click(container.querySelector('.user-question-edit-actions button:last-child')));
  expect(sendChat).toHaveBeenLastCalledWith(expect.objectContaining({ thread_id: original.thread_id, message: '자동문 5개소 설치 비용', restart: true }));
  expect(container.querySelectorAll('.user-bubble')).toHaveLength(3);
  expect(container.querySelector('.user-bubble').textContent).toBe('자동문 3개소 설치 비용');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(1);
});

test('editing can be cancelled without requests and cannot send an empty draft', async () => {
  await sendQuestion('원래 질문');
  act(() => Simulate.click(container.querySelector('[aria-label="질문 편집하기"]')));
  act(() => Simulate.change(container.querySelector('[aria-label="질문 편집"]'), { target: { value: '   ' } }));
  expect(container.querySelector('.user-question-edit-actions button:last-child').disabled).toBe(true);
  act(() => Simulate.click(container.querySelector('.user-question-edit-actions button')));
  expect(sendChat).toHaveBeenCalledTimes(1);
  expect(container.querySelector('.user-bubble').textContent).toBe('원래 질문');
});

async function sendQuestion(text) {
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: text } }));
  await act(async () => Simulate.click(container.querySelector('[aria-label="질문 보내기"]')));
}

test('guest conversations restore the selected thread on reload without sending another request', async () => {
  expect(container.querySelector('.chat-nav button').getAttribute('aria-current')).toBe('page');
  await sendQuestion('자동문 설치 비용');
  expect(container.querySelector('.chat-history-select').textContent).toBe('자동문 설치 비용');
  expect(container.querySelector('.chat-nav button').hasAttribute('aria-current')).toBe(false);
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  expect(container.querySelector('.welcome-header h2').textContent).toBe('무엇을 도와드릴까요?');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(1);
  await sendQuestion('콘크리트 타설 비용');
  expect(sendChat.mock.calls[1][0].thread_id).toBeNull();
  const firstChat = container.querySelector('.chat-history-select[title="자동문 설치 비용"]');
  act(() => Simulate.click(firstChat));
  expect(container.querySelector('.messages').textContent).toContain('답변: 자동문 설치 비용');
  expect(container.querySelector('.messages').textContent).not.toContain('콘크리트 타설 비용');
  await sendQuestion('조건 추가');
  expect(sendChat.mock.calls[2][0].thread_id).toBe('thread-자동문 설치 비용');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  expect(container.querySelector('.messages').textContent).toContain('답변: 자동문 설치 비용');
  expect(sendChat).toHaveBeenCalledTimes(3);
  await sendQuestion('새로고침 후 이어가기');
  expect(sendChat.mock.calls[3][0].thread_id).toBe('thread-자동문 설치 비용');
  expect(localStorage.getItem('poomsemi-chat-history-v1')).toBeNull();
});

test('guest rename preserves the thread and survives refresh without writing to the member API', async () => {
  await sendQuestion('처음 질문');
  act(() => Simulate.click(container.querySelector('.chat-history-more')));
  act(() => Simulate.click(document.querySelector('[aria-label="대화 이름 바꾸기"]')));
  const input = document.querySelector('.rename-dialog-input');
  expect(input.value).toBe('처음 질문');
  act(() => Simulate.change(input, { target: { value: '   벽체   견적  ' } }));
  await act(async () => Simulate.submit(document.querySelector('[role="dialog"] form')));
  expect(container.querySelector('.chat-history-select').textContent).toBe('벽체 견적');
  expect(renameConversation).not.toHaveBeenCalled();
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelector('.chat-history-select').textContent).toBe('벽체 견적');
  await sendQuestion('이어서 질문');
  expect(sendChat.mock.calls[1][0].thread_id).toBe('thread-처음 질문');
});

test('expired guest cache is not restored', async () => {
  await sendQuestion('만료된 질문');
  const cached = JSON.parse(sessionStorage.getItem('poomsemi-chat-tab-v1'));
  cached.updatedAt = Date.now() - 86400001;
  act(() => root.unmount());
  sessionStorage.setItem('poomsemi-chat-tab-v1', JSON.stringify(cached));
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelector('.welcome-header')).not.toBeNull();
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(0);
});

test('restore hides the new-chat screen and fetches transcript before the list finishes', async () => {
  act(() => root.unmount());
  sessionStorage.setItem('poomsemi-chat-tab-v1', JSON.stringify({ owner: 'A', updatedAt: Date.now(),
    store: { activeId: 'saved-id', conversations: [] } }));
  let finishAuth, finishList, finishTranscript;
  mockAuthClient = { auth: {
    getSession: jest.fn(() => new Promise(resolve => { finishAuth = resolve; })),
    onAuthStateChange: jest.fn(() => ({ data: { subscription: { unsubscribe: jest.fn() } } })),
  } };
  listConversations.mockImplementation(() => new Promise(resolve => { finishList = resolve; }));
  readConversation.mockImplementation(() => new Promise(resolve => { finishTranscript = resolve; }));
  root = createRoot(container);
  await act(async () => root.render(<React.StrictMode><App /></React.StrictMode>));
  expect(container.querySelector('.welcome-header')).toBeNull();
  expect(container.querySelector('.chat-restore-status').textContent).toContain('대화를 불러오고 있어요');
  expect(container.querySelector('.chat-nav button').hasAttribute('aria-current')).toBe(false);
  await act(async () => finishAuth({ data: { session: { user: { id: 'A' } } } }));
  expect(readConversation).toHaveBeenCalledWith('saved-id');
  expect(container.querySelector('.welcome-header')).toBeNull();
  await act(async () => finishTranscript([{ id: 'a1', role: 'assistant', response: response('saved-id', '복원된 답변') }]));
  expect(container.querySelector('.chat-restore-status')).not.toBeNull();
  await act(async () => finishList([{ id: 'saved-id', title: '이전 견적' }]));
  expect(container.querySelector('.chat-restore-status')).toBeNull();
  expect(container.querySelector('.messages').textContent).toContain('복원된 답변');
  expect(sendChat).not.toHaveBeenCalled();
});

test('another account selection is not restored or requested', async () => {
  act(() => root.unmount());
  sessionStorage.setItem('poomsemi-chat-tab-v1', JSON.stringify({ owner: 'A', updatedAt: Date.now(),
    store: { activeId: 'account-A-chat', conversations: [] } }));
  mockAuthClient = { auth: {
    getSession: jest.fn().mockResolvedValue({ data: { session: { user: { id: 'B' } } } }),
    onAuthStateChange: jest.fn(() => ({ data: { subscription: { unsubscribe: jest.fn() } } })),
  } };
  listConversations.mockResolvedValue([{ id: 'account-B-chat', title: 'B의 대화' }]);
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(readConversation).not.toHaveBeenCalled();
  expect(container.querySelector('.welcome-header')).not.toBeNull();
  expect(container.querySelector('.chat-history-select').textContent).toBe('B의 대화');
});

test('history switching and new chat are disabled while a response is pending', async () => {
  await sendQuestion('첫 질문');
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  let resolveResponse;
  sendChat.mockImplementationOnce(() => new Promise(resolve => { resolveResponse = resolve; }));
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '두 번째 질문' } }));
  act(() => Simulate.click(container.querySelector('[aria-label="질문 보내기"]')));
  expect(Array.from(container.querySelectorAll('.chat-history-select')).every(button => button.disabled)).toBe(true);
  expect(container.querySelector('[aria-label="새 대화 시작"]').disabled).toBe(true);
  expect(container.querySelector('.loading-indicator')).not.toBeNull();
  await act(async () => resolveResponse(response('second', '응답')));
  expect(container.querySelector('.chat-history-select').disabled).toBe(false);
  expect(container.querySelector('.loading-indicator')).toBeNull();
});

test('pending conversation deletion disables actions without showing AI thinking', async () => {
  await sendQuestion('삭제할 대화');
  let resolveDelete;
  deleteConversation.mockImplementationOnce(() => new Promise(resolve => { resolveDelete = resolve; }));
  act(() => Simulate.click(container.querySelector('.chat-history-more')));
  act(() => Simulate.click(document.querySelector('.chat-history-delete')));
  act(() => Simulate.click(document.querySelector('.delete-dialog-confirm')));
  expect(document.querySelector('.delete-dialog-confirm').textContent).toBe('삭제 중…');
  expect(container.querySelector('textarea').disabled).toBe(true);
  expect(container.querySelector('[aria-label="새 대화 시작"]').disabled).toBe(true);
  expect(container.querySelector('.loading-indicator')).toBeNull();
  await act(async () => resolveDelete());
  expect(container.querySelector('.loading-indicator')).toBeNull();
  expect(container.querySelector('.welcome-header')).not.toBeNull();
  expect(container.querySelector('textarea').disabled).toBe(false);
});

test('member history is restored after reload and replies keep the saved conversation ID', async () => {
  act(() => root.unmount());
  mockAuthClient = { auth: {
    getSession: jest.fn().mockResolvedValue({ data: { session: { user: { id: 'A', email: 'a@example.com' } } } }),
    onAuthStateChange: jest.fn(() => ({ data: { subscription: { unsubscribe: jest.fn() } } })),
    signOut: jest.fn().mockResolvedValue({ error: null }),
  } };
  listConversations.mockResolvedValue([{ id: 'saved-id', title: '저장된 견적' }]);
  readConversation.mockResolvedValue([
    { id: 'u1', role: 'user', text: '지난 질문' },
    { id: 'a1', role: 'assistant', response: response('saved-id', '지난 답변') },
  ]);
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelector('.chat-history-select').textContent).toBe('저장된 견적');
  await act(async () => Simulate.click(container.querySelector('.chat-history-select')));
  expect(readConversation).toHaveBeenCalledWith('saved-id');
  expect(container.querySelector('.messages').textContent).toContain('지난 답변');
  act(() => Simulate.click(container.querySelector('.chat-history-more')));
  act(() => Simulate.click(document.querySelector('[aria-label="대화 이름 바꾸기"]')));
  act(() => Simulate.change(document.querySelector('.rename-dialog-input'), { target: { value: '현장 A 견적' } }));
  renameConversation.mockRejectedValueOnce(new Error('SERVER_ERROR'));
  await act(async () => Simulate.submit(document.querySelector('[role="dialog"] form')));
  expect(document.querySelector('[role="alert"]').textContent).toContain('변경하지 못했습니다');
  expect(document.querySelector('.rename-dialog-input').value).toBe('현장 A 견적');
  expect(container.querySelector('.chat-history-select').textContent).toBe('저장된 견적');
  await act(async () => Simulate.submit(document.querySelector('[role="dialog"] form')));
  expect(renameConversation).toHaveBeenLastCalledWith('saved-id', '현장 A 견적', 'A');
  expect(container.querySelector('.chat-history-select').textContent).toBe('현장 A 견적');
  listConversations.mockResolvedValue([{ id: 'saved-id', title: '현장 A 견적' }]);
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelector('.messages').textContent).toContain('지난 답변');
  expect(container.querySelector('.chat-history-select').textContent).toBe('현장 A 견적');
  expect(sendChat).not.toHaveBeenCalled();
  expect(JSON.parse(sessionStorage.getItem('poomsemi-chat-tab-v1')).store.conversations).toEqual([]);
  await sendQuestion('이어서 질문');
  expect(sendChat.mock.calls[0][0]).toEqual(expect.objectContaining({
    thread_id: 'saved-id', conversation_id: 'saved-id', request_id: expect.any(String), user_label: '이어서 질문',
  }));
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<App />));
  expect(container.querySelector('.welcome-header')).not.toBeNull();
  await sendQuestion('새로운 회원 대화');
  expect(sendChat.mock.calls[1][0].conversation_id).not.toBe('saved-id');
  expect(sendChat.mock.calls[1][0].thread_id).toBeNull();
  const selectedId = sendChat.mock.calls[1][0].conversation_id;
  act(() => Simulate.click(container.querySelector('[aria-label="새로운 회원 대화 대화 메뉴"]')));
  act(() => Simulate.click(document.querySelector('.chat-history-delete')));
  await act(async () => Simulate.click(document.querySelector('.delete-dialog-confirm')));
  expect(deleteConversation).toHaveBeenCalledWith(selectedId, true, 'thread-새로운 회원 대화');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(1);
  act(() => Simulate.click(container.querySelector('[aria-label="계정 메뉴 열기"]')));
  await act(async () => Simulate.click(container.querySelector('.chat-account-logout')));
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(0);
});

test('conversation menu confirms deletion, preserves other chats, and keeps failed deletes visible', async () => {
  await sendQuestion('첫 번째');
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  await sendQuestion('두 번째');
  const firstId = container.querySelector('.chat-history-select[title="첫 번째"]').parentElement;
  act(() => Simulate.click(firstId.querySelector('.chat-history-more')));
  expect(container.querySelector('.messages').textContent).toContain('두 번째');
  act(() => Simulate.click(document.querySelector('.chat-history-delete')));
  act(() => Simulate.click(document.querySelector('.delete-dialog-cancel')));
  expect(deleteConversation).not.toHaveBeenCalled();
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  act(() => Simulate.click(firstId.querySelector('.chat-history-more')));
  act(() => Simulate.click(document.querySelector('.chat-history-delete')));
  deleteConversation.mockRejectedValueOnce(new Error('NETWORK_ERROR'));
  await act(async () => Simulate.click(document.querySelector('.delete-dialog-confirm')));
  expect(document.querySelector('[role="alert"]').textContent).toContain('삭제하지 못했습니다');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  await act(async () => Simulate.click(document.querySelector('.delete-dialog-confirm')));
  expect(deleteConversation).toHaveBeenLastCalledWith(expect.any(String), false, 'thread-첫 번째');
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(1);
  expect(container.querySelector('.messages').textContent).toContain('두 번째');
  act(() => Simulate.click(container.querySelector('.chat-history-more')));
  act(() => Simulate.click(document.querySelector('.chat-history-delete')));
  await act(async () => Simulate.click(document.querySelector('.delete-dialog-confirm')));
  expect(container.querySelector('.welcome-header h2').textContent).toBe('무엇을 도와드릴까요?');
});

test('failed guest import preserves both conversations and retries only the remaining temporary chat', async () => {
  await sendQuestion('첫 임시 견적');
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  await sendQuestion('둘째 임시 견적');
  importGuestConversation.mockImplementationOnce(async () => { throw new Error('NETWORK_ERROR'); });
  loginWithGoogle.mockResolvedValue({ id: 'A', email: 'a@example.com' });
  act(() => Simulate.click(container.querySelector('.chat-sidebar-login button')));
  await act(async () => Simulate.click(document.querySelector('.login-dialog-google')));
  expect(importGuestConversation).toHaveBeenCalledTimes(2);
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  expect(container.querySelector('.messages').textContent).toContain('둘째 임시 견적');
  expect(container.querySelector('.chat-history-select[title="둘째 임시 견적 · 임시"]')).not.toBeNull();
  expect(container.querySelector('textarea').disabled).toBe(true);
  expect(container.querySelector('[role="alert"]').textContent).toContain('새로고침 전에 다시 시도');
  await act(async () => Simulate.click(container.querySelector('.chat-migration-notice button')));
  expect(importGuestConversation).toHaveBeenCalledTimes(3);
  expect(importGuestConversation.mock.calls[2]).toEqual(importGuestConversation.mock.calls[0]);
  expect(container.querySelector('.chat-migration-notice')).toBeNull();
  expect(container.querySelector('textarea').disabled).toBe(false);
  expect(container.querySelectorAll('.chat-history-select')).toHaveLength(2);
  expect(container.querySelector('.chat-history-select[title="둘째 임시 견적"]')).not.toBeNull();
  await sendQuestion('이어서 질문');
  expect(sendChat.mock.calls[2][0].conversation_id).toBe(importGuestConversation.mock.calls[0][1]);
});

test('guest requests carry a request_id that is reused only when the same failed request is sent again', async () => {
  sendChat.mockRejectedValueOnce(new Error('NETWORK_ERROR'));
  await sendQuestion('같은 질문');
  await sendQuestion('같은 질문');
  await sendQuestion('다른 질문');
  const ids = sendChat.mock.calls.map(([body]) => body.request_id);
  expect(ids.every(Boolean)).toBe(true);
  expect(ids[1]).toBe(ids[0]);
  expect(ids[2]).not.toBe(ids[1]);
});

test('answers to server questions are sent with the question refs', async () => {
  const pending = { ...response('thread-q', '조건을 확인해 주세요.'), status: 'MISSING_INFO', inputs: [], conditions: [], evidence: [],
    questions: [{ name: 'concrete_supply', ask: '관급입니까?', choices: ['관급', '사급'], ref: 'i1:concrete_supply@v1@3' }] };
  sendChat.mockResolvedValueOnce(pending);
  await sendQuestion('비용 계산해줘');
  act(() => Simulate.click([...container.querySelectorAll('.choice-btn')].find(button => button.textContent === '관급')));
  await act(async () => Simulate.click(container.querySelector('.submit-answers-btn')));
  const body = sendChat.mock.calls[1][0];
  expect(body.answers).toEqual({ concrete_supply: '관급' });
  expect(body.refs).toEqual({ concrete_supply: 'i1:concrete_supply@v1@3' });
});

test('a repeated question name keeps the selection on the current card only', async () => {
  const scope = (ref) => ({ ...response('thread-s', '어느 견적인지 골라 주세요.'), status: 'MISSING_INFO', inputs: [], conditions: [], evidence: [],
    questions: [{ name: 'scope', ask: '지금 견적으로 계산할까요?', choices: ['지금 견적으로 계산', '새 견적 시작'], ref }] });
  sendChat.mockResolvedValueOnce(scope('scope@1@1')).mockResolvedValueOnce(scope('scope@1@2'));
  await sendQuestion('콘크리트 거푸집 비용');
  await sendQuestion('콘크리트 거푸집 비용');
  const latest = () => [...container.querySelectorAll('.question-list')].at(-1);
  act(() => Simulate.click([...latest().querySelectorAll('.choice-btn')].find(button => button.textContent === '새 견적 시작')));
  const selected = [...container.querySelectorAll('.choice-btn.selected')];
  expect(selected).toHaveLength(1);
  expect(latest().contains(selected[0])).toBe(true);
  await act(async () => Simulate.click(latest().querySelector('.submit-answers-btn')));
  expect(sendChat.mock.calls[2][0].refs).toEqual({ scope: 'scope@1@2' });
});

test('expired guest thread keeps history, stops repeat sends, and recovers into a new server thread on demand', async () => {
  await sendQuestion('첫 질문');
  sendChat.mockRejectedValueOnce(new Error('GUEST_EXPIRED'));
  await sendQuestion('이어서 질문');
  expect(sendChat).toHaveBeenCalledTimes(2);
  expect(container.querySelector('[role="alert"]').textContent).toContain('더 이어갈 수 없어요');
  expect(container.querySelector('textarea').disabled).toBe(true);
  expect(container.textContent).toContain('답변: 첫 질문');
  expect(container.querySelectorAll('.message.user')).toHaveLength(2);
  // 만료 상태에서는 다시 시도도 막아 같은 요청을 반복해서 실패시키지 않는다.
  expect([...container.querySelectorAll('.user-question-failed button')].every(button => button.disabled)).toBe(true);
  const expiredId = sendChat.mock.calls[1][0].request_id;

  await act(async () => Simulate.click([...container.querySelectorAll('button')].find(button => button.textContent === '새 대화로 이어서 질문하기')));
  expect(sendChat).toHaveBeenCalledTimes(2);  // 복구만으로는 아무것도 보내지 않는다
  expect(container.querySelector('.chat-thread-notice').textContent).toContain('이어지지 않아요');

  await act(async () => Simulate.click(container.querySelector('.user-question-failed button')));
  const retried = sendChat.mock.calls[2][0];
  expect(retried.thread_id).toBeNull();
  expect(retried.message).toBe('이어서 질문');
  expect(retried.request_id).not.toBe(expiredId);
  expect(container.querySelectorAll('.message.user')).toHaveLength(2);
  expect(container.querySelector('.user-question-failed')).toBeNull();
  expect(container.textContent).toContain('답변: 이어서 질문');
});

test('a failed question is retried in place with the same request_id instead of being appended again', async () => {
  sendChat.mockRejectedValueOnce(new Error('NETWORK_ERROR'));
  await sendQuestion('끊긴 질문');
  expect(container.querySelector('.user-question-failed').textContent).toContain('답변을 받지 못했어요');
  await act(async () => Simulate.click(container.querySelector('.user-question-failed button')));
  expect(sendChat.mock.calls[1][0].request_id).toBe(sendChat.mock.calls[0][0].request_id);
  expect(container.querySelectorAll('.message.user')).toHaveLength(1);
  expect(container.querySelector('.user-question-failed')).toBeNull();
});


test.each([false, true])('expired card answers stay above recovery notice without retry (refs: %s)', async withRefs => {
  const question = { name: 'concrete_supply', ask: '관급입니까?', choices: ['관급', '사급'],
    ...(withRefs ? { ref: 'i1:concrete_supply@v1@3' } : {}) };
  sendChat.mockResolvedValueOnce({ ...response('thread-card', '조건을 확인해 주세요.'), status: 'MISSING_INFO',
    inputs: [], conditions: [], evidence: [], questions: [question] });
  await sendQuestion('비용 계산해줘');
  act(() => Simulate.click([...container.querySelectorAll('.choice-btn')].find(button => button.textContent === '관급')));
  sendChat.mockRejectedValueOnce(new Error('GUEST_EXPIRED'));
  await act(async () => Simulate.click(container.querySelector('.submit-answers-btn')));
  expect(sendChat).toHaveBeenCalledTimes(2);
  expect(sendChat.mock.calls[1][0].answers).toEqual({ concrete_supply: '관급' });
  expect(sendChat.mock.calls[1][0].refs).toEqual(withRefs ? { concrete_supply: question.ref } : undefined);
  const failedTurn = container.querySelector('.user-question-failed').closest('.message');
  const originalTurns = [...container.querySelectorAll('.messages > .message.user, .messages > .message.assistant')];
  expect(container.querySelector('textarea').disabled).toBe(true);

  await act(async () => Simulate.click([...container.querySelectorAll('button')].find(button => button.textContent === '새 대화로 이어서 질문하기')));
  expect(sendChat).toHaveBeenCalledTimes(2);
  expect(container.querySelector('.user-question-failed').textContent).toContain('답변을 받지 못했어요');
  expect(container.querySelector('.user-question-failed button')).toBeNull();
  expect([...container.querySelectorAll('.messages > .message')].slice(0, -1)).toEqual(originalTurns);
  expect(container.querySelector('.user-question-failed').closest('.message')).toBe(failedTurn);
  expect([...container.querySelectorAll('.messages > .message')].at(-1).querySelector('.chat-thread-notice')).not.toBeNull();
  expect(container.querySelector('.chat-thread-notice').textContent).toContain('원하는 내용을 새로 입력해 주세요');
  expect(container.querySelector('textarea').disabled).toBe(false);

  await sendQuestion('새로 입력한 질문');
  expect(sendChat).toHaveBeenCalledTimes(3);
  expect(sendChat.mock.calls[2][0]).toEqual({ thread_id: null, message: '새로 입력한 질문', request_id: expect.any(String) });
  expect(container.querySelector('.user-question-failed button')).toBeNull();
});

test('expired resend recovers as message only with a new request_id', async () => {
  await sendQuestion('다시 보낼 질문');
  sendChat.mockRejectedValueOnce(new Error('GUEST_EXPIRED'));
  await act(async () => Simulate.click(container.querySelector('[aria-label="질문 다시 보내기"]')));
  const failed = sendChat.mock.calls[1][0];
  expect(failed).toEqual({ thread_id: 'thread-다시 보낼 질문', message: '다시 보낼 질문', restart: true, request_id: expect.any(String) });

  await act(async () => Simulate.click([...container.querySelectorAll('button')].find(button => button.textContent === '새 대화로 이어서 질문하기')));
  expect(sendChat).toHaveBeenCalledTimes(2);
  expect([...container.querySelectorAll('.messages > .message')].at(-1).querySelector('.user-question-failed button').disabled).toBe(false);
  await act(async () => Simulate.click(container.querySelector('.user-question-failed button')));
  expect(sendChat).toHaveBeenCalledTimes(3);
  const retried = sendChat.mock.calls[2][0];
  expect(retried).toEqual({ thread_id: null, message: '다시 보낼 질문', request_id: expect.any(String) });
  expect(retried.request_id).not.toBe(failed.request_id);
  expect(container.querySelectorAll('.message.user')).toHaveLength(2);
  expect(container.querySelector('.user-question-failed')).toBeNull();
});

test('card answers after a network error retry with the same body and request_id in the same thread', async () => {
  sendChat.mockResolvedValueOnce({ ...response('thread-network-card', '조건을 확인해 주세요.'), status: 'MISSING_INFO',
    inputs: [], conditions: [], evidence: [],
    questions: [{ name: 'concrete_supply', ask: '관급입니까?', choices: ['관급', '사급'], ref: 'i1:concrete_supply@v1@3' }] });
  await sendQuestion('비용 계산해줘');
  act(() => Simulate.click([...container.querySelectorAll('.choice-btn')].find(button => button.textContent === '관급')));
  sendChat.mockRejectedValueOnce(new Error('NETWORK_ERROR'));
  await act(async () => Simulate.click(container.querySelector('.submit-answers-btn')));
  const failed = sendChat.mock.calls[1][0];
  expect(failed.thread_id).toBe('thread-network-card');
  expect(failed.answers).toEqual({ concrete_supply: '관급' });
  expect(failed.refs).toEqual({ concrete_supply: 'i1:concrete_supply@v1@3' });
  await act(async () => Simulate.click(container.querySelector('.user-question-failed button')));
  expect(sendChat).toHaveBeenCalledTimes(3);
  expect(sendChat.mock.calls[2][0]).toEqual(failed);
  expect(container.querySelectorAll('.message.user')).toHaveLength(2);
  expect(container.querySelector('.user-question-failed')).toBeNull();
});

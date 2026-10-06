import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import App from './App';
import { sendChat, listConversations, readConversation } from './api';
import { loginWithGoogle } from './auth';

jest.mock('./api', () => ({ sendChat: jest.fn(), downloadEstimate: jest.fn(), listConversations: jest.fn(), readConversation: jest.fn() }));
let mockAuthClient = null;
jest.mock('./auth', () => ({ get authClient() { return mockAuthClient; }, AuthCallback: () => null, loginWithGoogle: jest.fn() }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => {} }));

let root, container;
const response = (thread_id, message) => ({ thread_id, message, status: 'OUT_OF_SCOPE', work: null, tables: { bill: null, statement_rows: [] }, search: { warnings: [], raw_warnings: [] } });
beforeEach(() => {
  mockAuthClient = null;
  loginWithGoogle.mockReset();
  listConversations.mockReset().mockResolvedValue([]);
  readConversation.mockReset().mockResolvedValue([]);
  global.IS_REACT_ACT_ENVIRONMENT = true;
  Element.prototype.scrollIntoView = jest.fn();
  localStorage.clear();
  window.history.replaceState({}, '', '/chat');
  sendChat.mockReset();
  sendChat.mockImplementation(async body => response(body.thread_id ?? `thread-${body.message}`, `답변: ${body.message}`));
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  act(() => root.render(<App />));
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
  act(() => Simulate.click(container.querySelector('[aria-label="계정 설정"]')));
  expect(document.querySelector('.settings-identity').textContent).toContain('a@example.com');
  await act(async () => Simulate.click(document.querySelector('.settings-logout')));
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(0);
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

async function sendQuestion(text) {
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: text } }));
  await act(async () => Simulate.click(container.querySelector('[aria-label="질문 보내기"]')));
}

test('guest conversations keep their original thread within the tab and disappear on reload', async () => {
  expect(container.querySelector('.chat-nav button').getAttribute('aria-current')).toBe('page');
  await sendQuestion('자동문 설치 비용');
  expect(container.querySelector('.chat-history button').textContent).toBe('자동문 설치 비용');
  expect(container.querySelector('.chat-nav button').hasAttribute('aria-current')).toBe(false);
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  expect(container.querySelector('.welcome-header h2').textContent).toBe('무엇을 도와드릴까요?');
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(1);
  await sendQuestion('콘크리트 타설 비용');
  expect(sendChat.mock.calls[1][0].thread_id).toBeNull();
  const firstChat = container.querySelector('.chat-history button[title="자동문 설치 비용"]');
  act(() => Simulate.click(firstChat));
  expect(container.querySelector('.messages').textContent).toContain('답변: 자동문 설치 비용');
  expect(container.querySelector('.messages').textContent).not.toContain('콘크리트 타설 비용');
  await sendQuestion('조건 추가');
  expect(sendChat.mock.calls[2][0].thread_id).toBe('thread-자동문 설치 비용');
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(2);
  act(() => root.unmount());
  root = createRoot(container);
  act(() => root.render(<App />));
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(0);
  expect(container.querySelector('.welcome-header h2').textContent).toBe('무엇을 도와드릴까요?');
  expect(localStorage.getItem('poomsemi-chat-history-v1')).toBeNull();
});

test('history switching and new chat are disabled while a response is pending', async () => {
  await sendQuestion('첫 질문');
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  let resolveResponse;
  sendChat.mockImplementationOnce(() => new Promise(resolve => { resolveResponse = resolve; }));
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '두 번째 질문' } }));
  act(() => Simulate.click(container.querySelector('[aria-label="질문 보내기"]')));
  expect(Array.from(container.querySelectorAll('.chat-history button')).every(button => button.disabled)).toBe(true);
  expect(container.querySelector('[aria-label="새 대화 시작"]').disabled).toBe(true);
  await act(async () => resolveResponse(response('second', '응답')));
  expect(container.querySelector('.chat-history button').disabled).toBe(false);
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
  expect(container.querySelector('.chat-history button').textContent).toBe('저장된 견적');
  await act(async () => Simulate.click(container.querySelector('.chat-history button')));
  expect(readConversation).toHaveBeenCalledWith('saved-id');
  expect(container.querySelector('.messages').textContent).toContain('지난 답변');
  await sendQuestion('이어서 질문');
  expect(sendChat.mock.calls[0][0]).toEqual(expect.objectContaining({
    thread_id: 'saved-id', conversation_id: 'saved-id', request_id: expect.any(String), user_label: '이어서 질문',
  }));
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  await sendQuestion('새로운 회원 대화');
  expect(sendChat.mock.calls[1][0].conversation_id).not.toBe('saved-id');
  expect(sendChat.mock.calls[1][0].thread_id).toBeNull();
  act(() => Simulate.click(container.querySelector('[aria-label="계정 설정"]')));
  await act(async () => Simulate.click(document.querySelector('.settings-logout')));
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(0);
});

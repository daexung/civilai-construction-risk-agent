import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import App from './App';
import { sendChat } from './api';

jest.mock('./api', () => ({ sendChat: jest.fn(), exportUrl: jest.fn() }));
jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => {} }));

let root, container;
const response = (thread_id, message) => ({ thread_id, message, status: 'OUT_OF_SCOPE', work: null, tables: { bill: null, statement_rows: [] }, search: { warnings: [], raw_warnings: [] } });
beforeEach(() => {
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
afterEach(() => { act(() => root.unmount()); container.remove(); localStorage.clear(); });

async function sendQuestion(text) {
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: text } }));
  await act(async () => Simulate.click(container.querySelector('[aria-label="질문 보내기"]')));
}

test('new conversations get first-question titles, switch with their original thread and survive reload', async () => {
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
  expect(container.querySelectorAll('.chat-history button')).toHaveLength(2);
  expect(container.querySelector('.messages').textContent).toContain('조건 추가');
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

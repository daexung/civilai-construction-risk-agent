import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import ChatArea from './ChatArea';
import { EXAMPLE_QUESTIONS } from '../examples';

jest.mock('react-markdown', () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => {} }));

let root, container, props;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  Element.prototype.scrollIntoView = jest.fn();
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  props = { turns: [], loading: false, onSendMessage: jest.fn(), onSendAnswers: jest.fn(), onChangeConditions: jest.fn(), onNewChat: jest.fn(), onSendExample: jest.fn() };
  act(() => root.render(<ChatArea {...props} />));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

test('composer sends trimmed text, preserves Shift+Enter and Korean IME composition', () => {
  const input = container.querySelector('textarea');
  act(() => Simulate.change(input, { target: { value: '  자동문 3개소  ' } }));
  act(() => Simulate.keyDown(input, { key: 'Enter', shiftKey: true, nativeEvent: {} }));
  act(() => Simulate.keyDown(input, { key: 'Enter', nativeEvent: { isComposing: true } }));
  expect(props.onSendMessage).not.toHaveBeenCalled();
  act(() => Simulate.keyDown(input, { key: 'Enter', nativeEvent: { isComposing: false } }));
  expect(props.onSendMessage).toHaveBeenCalledWith('자동문 3개소');
  expect(input.value).toBe('');
});

test('examples retain full prompts and new chat clears an unsent draft', () => {
  act(() => Simulate.click(container.querySelector('.example-btn')));
  expect(props.onSendExample).toHaveBeenCalledWith(EXAMPLE_QUESTIONS[0].text);
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '임시 질문' } }));
  act(() => Simulate.click(container.querySelector('[aria-label="새 대화 시작"]')));
  expect(props.onNewChat).toHaveBeenCalledTimes(1);
  expect(container.querySelector('textarea').value).toBe('');
  act(() => root.render(<ChatArea {...props} loading />));
  expect(container.querySelector('[aria-label="질문 보내기"]').disabled).toBe(true);
  expect(container.querySelector('[aria-label="새 대화 시작"]').disabled).toBe(true);
  expect(container.querySelector('.example-btn').disabled).toBe(true);
});

test('sidebar can close and reopen with settings, feedback and login controls', () => {
  expect(container.querySelector('.chat-sidebar img')).toBeNull();
  expect(container.querySelector('.chat-sidebar-brand a').getAttribute('href')).toBe('/');
  expect(container.querySelector('.chat-sidebar').textContent).toContain('설정');
  expect(container.querySelector('.chat-sidebar').textContent).toContain('피드백 남기기');
  expect(container.querySelector('.chat-sidebar-login button').textContent).toBe('로그인');
  act(() => Simulate.click(container.querySelector('[aria-label="사이드바 닫기"]')));
  expect(container.querySelector('.chat-sidebar')).toBeNull();
  act(() => Simulate.click(container.querySelector('[aria-label="사이드바 열기"]')));
  expect(container.querySelector('.chat-sidebar-login button')).not.toBeNull();
});

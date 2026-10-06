import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import ChatArea from './ChatArea';
import { EXAMPLE_QUESTIONS } from '../examples';
import demo from '../landing/demo.json';

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

test('estimate header only shows elapsed time and conditions still submit the same values', () => {
  const response = demo.response;
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'a1', role: 'assistant', response, elapsedMs: 2300 }]} />));
  const header = container.querySelector('.assistant-card-header');
  expect(header.textContent).toBe('2.3초 동안 생각함');
  expect(header.querySelector('button')).toBeNull();
  expect(container.querySelector('.source-list summary').textContent).toContain('품셈 근거와 원문');
  expect(container.querySelector('.source-list').textContent).toContain(response.work.title);
  const toggle = container.querySelector('.conditions-toggle');
  expect(toggle.textContent).toBe('현장 조건 반영하기');
  act(() => Simulate.click(toggle));
  expect(toggle.getAttribute('aria-expanded')).toBe('true');
  expect(container.querySelector('.conditions-panel').textContent).toContain('1회가 차감');
  act(() => Simulate.click(container.querySelector('.conditions-panel .submit-answers-btn')));
  expect(props.onChangeConditions).toHaveBeenCalledWith('a1', Object.fromEntries(response.conditions.map(field => [field.name, field.value])));
});

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

test('guest sidebar follows server usage, distinguishes shared limits and hides on login', () => {
  expect(container.querySelector('.chat-guest-usage').textContent).toContain('확인 중');
  const usage = { remaining: 3, limit: 5, service_remaining: 490 };
  act(() => root.render(<ChatArea {...props} usage={usage} />));
  expect(container.querySelector('.chat-guest-usage').textContent).toContain('3회');
  act(() => root.render(<ChatArea {...props} usage={{ ...usage, remaining: 0 }} />));
  expect(container.querySelector('.chat-guest-usage').textContent).toContain('모두 사용');
  act(() => root.render(<ChatArea {...props} usage={{ ...usage, service_remaining: 0 }} />));
  expect(container.querySelector('.chat-guest-usage').textContent).toContain('서비스 전체 한도');
  act(() => root.render(<ChatArea {...props} accountLabel="테스트 회원" usage={usage} />));
  expect(container.querySelector('.chat-guest-usage')).toBeNull();
});

test('missing pump conditions explain the request and preserve only server questions', () => {
  const questions = [{ name: 'slump_band', ask: '슬럼프는?', choices: ['15㎝', '18㎝이상'] }];
  const response = { ...demo.response, status: 'MISSING_INFO', answer: null, message: '조건을 확인해 주세요.', result: null, questions };
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'q1', role: 'assistant', response }]} />));
  expect(container.querySelector('[aria-label="추가 조건 안내"]').textContent).toContain('시공량과 비용이 달라져요');
  expect(container.querySelectorAll('.question-card')).toHaveLength(1);
  expect(container.querySelector('.question-list').textContent).not.toContain('물량은');
});

test('unit-based estimates state their scope and actual separately counted work', () => {
  const response = { ...demo.response, work: { ...demo.response.work, title: '자동문 설치' },
    result: { ...demo.response.result, daily_volume: null, not_calculated: [{ item: '유리공사, 전기 및 통신공사' }] } };
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'a1', role: 'assistant', response }]} />));
  const guidance = container.querySelector('[aria-label="계산 범위 안내"]');
  expect(guidance.textContent).toContain('자동문 설치의 계산 범위');
  expect(guidance.textContent).toContain('단위당 작업 품');
  expect(guidance.textContent).toContain('유리공사, 전기 및 통신공사');
});

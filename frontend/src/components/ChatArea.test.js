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

test('bundle estimate keeps main tabs and shows each work as an expandable section', () => {
  const bill = (name, total) => ({ name, spec: '', unit: '㎥', quantity: '10', partial: false, total,
    unit_price: { 재료비: null, 노무비: '1000', 경비: '0' }, amount: { 재료비: null, 노무비: total, 경비: '0' } });
  const response = { ...demo.response, answer_id: 'bundle-1', status: 'PARTIAL', result: null, priced: null, work: null,
    items: [
      { query: '레미콘 150㎥', status: 'PARTIAL', reason: '', work: { title: '6-1-1 레미콘 타설' }, inputs: demo.response.inputs,
        result: demo.response.result, priced: { ...demo.response.priced, reference_amounts: { total: '1000' } } },
      // 계산 보류 항목도 result(보류 사유 형태)를 가진다. ComputedCard로 넘기면 안 된다.
      { query: '벽체 260㎥ 펌프차', status: 'BLOCKED', reason: '재셋팅 조건은 원문 근거가 불명확합니다', work: { title: '6-1-4 펌프차 타설' },
        inputs: [], result: { reason: '재셋팅', input: 'reset_status', citations: [] }, priced: null },
    ],
    tables: { ...demo.response.tables, bills: [bill('레미콘', '1000'), bill('철근', '2000')] } };
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'a1', role: 'assistant', response }]} />));
  expect(container.querySelector('.estimate-guidance').textContent).toContain('묶음 견적의 계산 범위');
  expect(container.querySelector('.estimate-guidance').textContent).toContain('전체 공사비는 아니에요');
  const mainTabs = [...container.querySelectorAll('.assistant-card > .estimate-tabs [role="tab"]')].map(tab => tab.textContent);
  expect(mainTabs).toEqual(expect.arrayContaining(['원가계산서', '내역서']));
  act(() => Simulate.click([...container.querySelectorAll('[role="tab"]')].find(tab => tab.textContent === '내역서')));
  const rows = container.querySelectorAll('.bill-table tbody tr');
  expect(rows).toHaveLength(3);
  expect(rows[2].textContent).toContain('3,000');
  const items = container.querySelectorAll('.bundle-item');
  expect(items).toHaveLength(2);
  expect(items[0].querySelector('summary').textContent).toContain('직접비 1,000원');
  expect(items[1].querySelector('summary').textContent).toContain('금액 미포함');
  expect(items[1].textContent).toContain('계산 보류: 재셋팅 조건은 원문 근거가 불명확합니다');
  expect(items[1].querySelector('.computed-card')).toBeNull();
  const detailTabs = [...items[0].querySelectorAll('[role="tab"]')].map(tab => tab.textContent);
  expect(detailTabs.some(label => label.startsWith('일위대가표'))).toBe(true);
  expect(detailTabs).toContain('산출근거');
  expect(container.querySelector('.export-link')).not.toBeNull();
  expect(container.querySelector('.estimate-review-notice')).not.toBeNull();
  expect(container.querySelector('.answer-feedback')).not.toBeNull();
  expect(container.querySelector('.conditions-toggle')).not.toBeNull();
});

test('split confirmation questions explain what is being asked and why it is asked again', () => {
  const ask = (questions) => ({ ...demo.response, status: 'MISSING_INFO', result: null, priced: null, work: null, items: [],
    message: '여러 공종으로 나눌지 확인이 필요해요.', answer: null, questions });
  const attach = ask([{ name: 'attach_3', ask: '‘슬럼프 15cm’은(는) 어느 공종의 조건인가요?', choices: ['1번(레미콘 100m3)', '2번(자동문 3개소)', '모든 공종'],
    reason: '아직 답하지 않은 질문이에요.' }]);
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'a1', role: 'assistant', response: attach }]} />));
  expect(container.querySelector('.estimate-guidance').textContent).toContain('조건이 어느 공종에 해당하는지 확인이 필요해요');
  expect(container.textContent).toContain('아직 답하지 않은 질문이에요.');
  const named = ask([{ name: 'named', ask: '‘도장’, ‘자동문 설치’을(를) 각각 따로 견적할까요?', choices: ['각각 따로 견적', '하나의 공종으로'] }]);
  act(() => root.render(<ChatArea {...props} turns={[{ id: 'a2', role: 'assistant', response: named }]} />));
  expect(container.querySelector('.estimate-guidance').textContent).toContain('여러 공종인지 확인이 필요해요');
});

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import Landing from './Landing';

let root;
let container;
beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  global.IS_REACT_ACT_ENVIRONMENT = true;
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

test('landing describes the current service and preserves its real estimate preview', () => {
  act(() => root.render(<Landing onStart={() => {}} onExample={() => {}} />));
  expect(container.textContent).toContain('품셈AI');
  expect(container.textContent).toContain('공사비 견적');
  expect(container.textContent).toContain('품셈 상담');
  expect(container.textContent).toContain('엑셀 출력');
  expect(container.textContent).not.toMatch(/기상|대기비|로그인/);
  expect(container.textContent).toContain('도급액');
  expect(container.textContent).toContain('미산정 항목');
  const calculationToggle = container.querySelector('.preview-disclosure > button');
  expect(calculationToggle.getAttribute('aria-expanded')).toBe('false');
  act(() => Simulate.click(calculationToggle));
  expect(calculationToggle.getAttribute('aria-expanded')).toBe('true');
  expect(container.querySelector('.preview-disclosure-content').hidden).toBe(false);
  const tabs = container.querySelectorAll('[role="tab"]');
  act(() => Simulate.click(tabs[1]));
  expect(tabs[1].getAttribute('aria-selected')).toBe('true');
  expect(container.querySelector('.preview-unit-table')).not.toBeNull();
  act(() => Simulate.keyDown(tabs[1], { key: 'ArrowRight' }));
  expect(tabs[2].getAttribute('aria-selected')).toBe('true');
  expect(container.querySelector('.preview-basis')).not.toBeNull();
});

test('start and example actions use the current chat integration', () => {
  const onStart = jest.fn();
  const onExample = jest.fn();
  act(() => root.render(<Landing onStart={onStart} onExample={onExample} />));
  const startLink = container.querySelector('.lp-nav-demo');
  expect(startLink.getAttribute('href')).toBe('/chat');
  act(() => startLink.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 })));
  expect(onStart).toHaveBeenCalledTimes(1);
  act(() => Simulate.click(container.querySelector('.lp-example-button')));
  expect(onExample).toHaveBeenCalledWith('철근콘크리트 벽체 260㎥를 32m 붐 펌프차로 타설하면 비용이 얼마나 드나요?');
});

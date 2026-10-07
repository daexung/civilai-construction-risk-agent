import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import BetaNotice from './BetaNotice';

const key = 'poomsemi.betaNotice.hiddenDay';
let root;
let container;
let now;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  now = jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-06T14:59:00Z'));
  container = document.createElement('div');
  container.className = 'civil-landing';
  document.body.appendChild(container);
  root = createRoot(container);
  global.IS_REACT_ACT_ENVIRONMENT = true;
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  jest.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});
const render = (onStart = () => {}) => act(() => root.render(<BetaNotice onStart={onStart} />));
const reopen = () => { act(() => root.render(null)); render(); };
const checkToday = () => act(() => Simulate.change(document.querySelector('.beta-notice input'), { target: { checked: true } }));
const close = () => act(() => Simulate.click(document.querySelector('.beta-notice-close')));

test('ordinary dismissal allows the notice on the next visit and restores background access', () => {
  render();
  expect(document.querySelector('[role="dialog"]').textContent).toContain('20');
  expect(document.querySelector('.beta-notice-scope').textContent).toContain('3개 공종');
  expect(document.querySelector('.beta-notice-scope').textContent).toContain('추후 업데이트');
  expect(container.hasAttribute('inert')).toBe(true);
  expect(document.activeElement).toBe(document.querySelector('.beta-notice-title'));
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })));
  expect(document.activeElement).toBe(document.querySelector('.beta-notice-footer input'));
  close();
  expect(container.hasAttribute('inert')).toBe(false);
  expect(localStorage.getItem(key)).toBeNull();
  reopen();
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
});

test('today dismissal expires at Korean midnight rather than 24 hours later', () => {
  render();
  checkToday();
  close();
  expect(localStorage.getItem(key)).toBe('2026-10-06');
  reopen();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  now.mockReturnValue(Date.parse('2026-10-06T15:00:00Z'));
  reopen();
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
});

test('starting saves the dismissal preference and opens the existing chat flow', () => {
  const onStart = jest.fn();
  render(onStart);
  checkToday();
  act(() => Simulate.click(document.querySelector('.beta-notice-start')));
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(localStorage.getItem(key)).toBe('2026-10-06');
});

test('blocked browser storage still allows showing and closing via Escape', () => {
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  render();
  checkToday();
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(container.hasAttribute('inert')).toBe(false);
});


test('chat feedback dismisses the notice and shows it on the next visit unless today is checked', () => {
  container.className = 'app';
  const onFeedback = jest.fn();
  const renderChat = () => act(() => root.render(<BetaNotice variant="chat" onStart={() => {}} onFeedback={onFeedback} />));
  renderChat();
  expect(document.querySelector('.beta-notice-scope').textContent).toContain('3개 공종');
  expect(document.querySelector('.beta-notice-feedback').textContent).toContain('정확하지');
  expect(container.hasAttribute('inert')).toBe(true);
  act(() => Simulate.click(document.querySelector('.beta-notice-feedback-action')));
  expect(onFeedback).toHaveBeenCalledTimes(1);
  expect(container.hasAttribute('inert')).toBe(false);
  act(() => root.render(null));
  renderChat();
  expect(document.querySelector('.beta-notice')).not.toBeNull();
  now.mockReturnValue(Date.parse('2026-10-06T15:00:00Z'));
  act(() => root.render(null));
  renderChat();
  expect(document.querySelector('.beta-notice')).not.toBeNull();
});

test('hiding the landing notice does not hide the chat notice', () => {
  render();
  checkToday();
  close();
  act(() => root.render(null));
  container.className = 'app';
  act(() => root.render(<BetaNotice variant="chat" onStart={() => {}} />));
  expect(document.querySelector('.beta-notice')).not.toBeNull();
  checkToday();
  close();
  sessionStorage.clear();
  act(() => root.render(null));
  act(() => root.render(<BetaNotice variant="chat" onStart={() => {}} />));
  expect(document.querySelector('.beta-notice')).toBeNull();
});

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import AnswerFeedback from './AnswerFeedback';
import { sendAnswerFeedback } from '../api';

jest.mock('../api', () => ({ sendAnswerFeedback: jest.fn(), UsageError: class extends Error {} }));
let root, container;
const response = { answer_id: 'answer-one', thread_id: 'thread-one', status: 'ANSWERED' };
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container); sendAnswerFeedback.mockReset().mockResolvedValue({ rating: 'good' });
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = (ordinal = 1, props = {}) => act(() => root.render(<AnswerFeedback response={response} ordinal={ordinal} {...props} />));

test('asks on answers 1, 4 and 7 and saves positive ratings only after receipt', async () => {
  for (const ordinal of [1, 2, 3, 4, 7]) {
    render(ordinal);
    expect(!!container.querySelector('.answer-feedback-prompt')).toBe([1, 4, 7].includes(ordinal));
  }
  const onSaved = jest.fn(); render(1, { userId: 'member-A', onSaved });
  await act(async () => Simulate.click(container.querySelector('[aria-label="도움됐어요"]')));
  expect(sendAnswerFeedback).toHaveBeenCalledWith({ answer_id: 'answer-one', thread_id: 'thread-one', rating: 'good' }, 'member-A');
  expect(container.querySelector('[aria-label="도움됐어요"]').getAttribute('aria-pressed')).toBe('true');
  expect(onSaved).toHaveBeenCalledTimes(1);
});

test('negative ratings require a reason, preserve input after failure and retry without AI requests', async () => {
  render();
  act(() => Simulate.click(container.querySelector('[aria-label="아쉬워요"]')));
  expect(container.querySelector('[type="submit"]').disabled).toBe(true);
  act(() => Simulate.change(container.querySelector('[value="evidence"]')));
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '근거를 더 보여 주세요' } }));
  sendAnswerFeedback.mockRejectedValueOnce(new Error('NETWORK_ERROR'));
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(container.querySelector('textarea').value).toBe('근거를 더 보여 주세요');
  expect(container.querySelector('[aria-label="아쉬워요"]').getAttribute('aria-pressed')).toBe('false');
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(sendAnswerFeedback).toHaveBeenLastCalledWith({ answer_id: 'answer-one', thread_id: 'thread-one', rating: 'bad', reason: 'evidence', comment: '근거를 더 보여 주세요' }, undefined);
  expect(container.querySelector('form')).toBeNull();
  expect(container.querySelector('[aria-label="아쉬워요"]').getAttribute('aria-pressed')).toBe('true');
});

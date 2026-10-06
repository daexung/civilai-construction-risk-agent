import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import FeedbackDialog from './FeedbackDialog';
import { sendFeedback, UsageError } from '../api';

jest.mock('../api', () => ({ sendFeedback: jest.fn(), UsageError: class UsageError extends Error {} }));
let container, root, close;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); container.className = 'app'; document.body.appendChild(container);
  root = createRoot(container); close = jest.fn(); sendFeedback.mockReset();
  act(() => root.render(<FeedbackDialog userId="member-A" onClose={close} />));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const edit = text => act(() => Simulate.change(document.querySelector('textarea'), { target: { value: text } }));
const submit = () => act(async () => Simulate.submit(document.querySelector('form')));

test('feedback requires meaningful input and keyboard focus stays in the dialog', () => {
  expect(document.activeElement).toBe(document.querySelector('textarea'));
  edit('    ');
  expect(document.querySelector('.feedback-submit').disabled).toBe(true);
  const last = document.querySelector('.feedback-submit');
  edit('a useful suggestion');
  act(() => last.focus());
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })));
  expect(document.activeElement).toBe(document.querySelector('.feedback-close'));
});

test('failed requests preserve input and retry identity, then show success', async () => {
  sendFeedback.mockRejectedValueOnce(new UsageError('잠시 후 다시 보내 주세요.')).mockResolvedValue({ id: 'received' });
  edit('  improve the estimate  ');
  await submit();
  expect(document.querySelector('textarea').value).toBe('  improve the estimate  ');
  expect(document.querySelector('[role="alert"]').textContent).toBe('잠시 후 다시 보내 주세요.');
  await submit();
  expect(sendFeedback.mock.calls[0]).toEqual(sendFeedback.mock.calls[1]);
  expect(sendFeedback.mock.calls[0][0].message).toBe('improve the estimate');
  expect(sendFeedback.mock.calls[0][1]).toBe('member-A');
  expect(document.querySelector('[role="dialog"]').textContent).toContain('피드백을 접수했어요');
  expect(document.querySelector('textarea')).toBeNull();
});

test('pending submissions cannot duplicate or dismiss; edited feedback gets a new identity', async () => {
  let reject;
  sendFeedback.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  edit('an error happened');
  act(() => Simulate.submit(document.querySelector('form')));
  act(() => Simulate.submit(document.querySelector('form')));
  act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(sendFeedback).toHaveBeenCalledTimes(1);
  expect(close).not.toHaveBeenCalled();
  await act(async () => reject(new Error('NETWORK_ERROR')));
  edit('a different error happened'); sendFeedback.mockResolvedValue({ id: 'ok' });
  await submit();
  expect(sendFeedback.mock.calls[0][0].request_id).not.toBe(sendFeedback.mock.calls[1][0].request_id);
});

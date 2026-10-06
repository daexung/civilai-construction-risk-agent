import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import DeleteAccountDialog from './DeleteAccountDialog';
import { beginAccountDeletion, deleteAccount } from '../api';
import { loginWithGoogle } from '../auth';
jest.mock('../api', () => ({ beginAccountDeletion: jest.fn(), deleteAccount: jest.fn() }));
jest.mock('../auth', () => ({ loginWithGoogle: jest.fn() }));
let root, container, deleted;
beforeEach(async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); container.className = 'app'; document.body.appendChild(container);
  root = createRoot(container); deleted = jest.fn();
  beginAccountDeletion.mockReset().mockResolvedValue({ challenge_id: 'challenge' });
  deleteAccount.mockReset().mockResolvedValue(undefined);
  loginWithGoogle.mockReset().mockResolvedValue({ id: 'A' });
  await act(async () => root.render(<DeleteAccountDialog userId="A" email="fixture@example.invalid" onClose={() => {}} onDeleted={deleted} />));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
test('deletion requires Google account verification and an explicit confirmation', async () => {
  expect(deleteAccount).not.toHaveBeenCalled();
  await act(async () => Simulate.click(document.querySelector('.feedback-submit')));
  expect(loginWithGoogle).toHaveBeenCalledWith(true);
  expect(document.querySelector('.account-delete-submit').disabled).toBe(true);
  act(() => Simulate.change(document.querySelector('input'), { target: { value: '탈퇴' } }));
  await act(async () => Simulate.click(document.querySelector('.account-delete-submit')));
  expect(deleteAccount).toHaveBeenCalledWith('challenge', 'A');
  expect(deleted).toHaveBeenCalledTimes(1);
});
test('another Google account never enables deletion of the original account', async () => {
  loginWithGoogle.mockResolvedValue({ id: 'B' });
  await act(async () => Simulate.click(document.querySelector('.feedback-submit')));
  expect(document.querySelector('[role="alert"]').textContent).toContain('같은 Google 계정');
  expect(document.querySelector('input')).toBeNull();
  expect(deleteAccount).not.toHaveBeenCalled();
});

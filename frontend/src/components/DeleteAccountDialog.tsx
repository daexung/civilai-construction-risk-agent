import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { beginAccountDeletion, deleteAccount } from '../api';
import { loginWithGoogle } from '../auth';
import { CONTACT_EMAIL } from '../contact';
import useDialogFocus from './useDialogFocus';
import './FeedbackDialog.css';
import './DeleteAccountDialog.css';

export default function DeleteAccountDialog({ userId, email, onClose, onDeleted }: {
  userId: string; email: string; onClose: () => void; onDeleted: () => void;
}) {
  const title = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const pending = useRef(false);
  const [challenge, setChallenge] = useState('');
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  useDialogFocus(dialog, onClose, busy, '.account-delete-heading');
  useEffect(() => {
    let active = true;
    beginAccountDeletion(userId).then(value => { if (active) setChallenge(value.challenge_id); })
      .catch(() => { if (active) setError('탈퇴 확인을 시작하지 못했습니다. 잠시 후 다시 열거나 문의 이메일로 연락해 주세요.'); });
    return () => { active = false; };
  }, [userId]);
  const verify = async () => {
    if (pending.current || !challenge) return;
    pending.current = true; setBusy(true); setError('');
    try {
      const user = await loginWithGoogle(true);
      if (user.id !== userId) throw new Error('현재 로그인한 계정과 같은 Google 계정을 선택해 주세요.');
      setVerified(true);
      window.requestAnimationFrame(() => dialog.current?.querySelector<HTMLInputElement>('input')?.focus());
    } catch (reason) { setError(reason instanceof Error ? reason.message : '계정을 확인하지 못했습니다.'); }
    finally { pending.current = false; setBusy(false); }
  };
  const remove = async () => {
    if (pending.current || !verified || confirmation !== '탈퇴') return;
    pending.current = true; setBusy(true); setError('');
    try { await deleteAccount(challenge, userId); onDeleted(); }
    catch { setError('탈퇴 처리를 완료하지 못했습니다. 다시 시도하거나 문의 이메일로 연락해 주세요.'); }
    finally { pending.current = false; setBusy(false); }
  };
  return createPortal(<div className="feedback-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <div className="feedback-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={title} tabIndex={-1} aria-busy={busy}>
      <button className="feedback-close" disabled={busy} aria-label="회원탈퇴 창 닫기" onClick={onClose}><X size={20} /></button>
      <h2 id={title} className="account-delete-heading" tabIndex={-1}>회원탈퇴</h2>
      <p>{email}</p>
      <ul className="account-delete-notice">
        <li>계정, 저장된 대화와 견적, 직접 남긴 피드백을 삭제하며 복구할 수 없습니다.</li>
        <li>같은 Google 계정으로 바로 재가입할 수 있지만, 당일 사용량은 초기화되지 않습니다.</li>
        <li>반복 가입으로 한도를 우회하는 것을 막기 위해 Google 식별자의 해시와 사용량 집계는 7일보다 오래된 날짜를 정리할 때까지 별도로 보관합니다.</li>
      </ul>
      {!verified ? <>
        <p>Google 로그인 계정이므로 별도 비밀번호 없이 Google 계정을 다시 확인합니다. Google 계정 자체는 삭제되지 않습니다.</p>
        <button className="feedback-submit" disabled={busy || !challenge} onClick={verify}>{busy ? '계정 확인 중…' : 'Google 계정 다시 확인'}</button>
      </> : <>
        <label htmlFor={`${title}-confirm`}>탈퇴하려면 아래에 ‘탈퇴’를 입력해 주세요.</label>
        <input id={`${title}-confirm`} className="account-delete-input" value={confirmation} disabled={busy} autoComplete="off" onChange={event => setConfirmation(event.target.value)} />
        <button className="feedback-submit account-delete-submit" disabled={busy || confirmation !== '탈퇴'} onClick={remove}>{busy ? '탈퇴 처리 중…' : '계정 영구 삭제'}</button>
      </>}
      {error && <p className="feedback-error" role="alert">{error}</p>}
      <p className="feedback-notice">문의: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></p>
    </div>
  </div>, document.body);
}

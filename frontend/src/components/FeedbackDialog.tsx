import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, X } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import { sendFeedback, UsageError } from '../api';
import { trackEvent } from '../analytics';
import useDialogFocus from './useDialogFocus';
import { CONTACT_EMAIL } from '../contact';
import './FeedbackDialog.css';

export default function FeedbackDialog({ userId, onClose }: { userId?: string; onClose: () => void }) {
  const titleId = useId();
  const descriptionId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const requestId = useRef(uuidv4());
  const pending = useRef(false);
  const [category, setCategory] = useState<'bug' | 'suggestion' | 'other'>('suggestion');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [received, setReceived] = useState(false);
  const [error, setError] = useState('');
  useDialogFocus(dialog, onClose, busy, '.feedback-message');
  const changed = () => { requestId.current = uuidv4(); setError(''); };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (pending.current || message.trim().length < 5) return;
    pending.current = true; setBusy(true); setError('');
    try {
      await sendFeedback({ request_id: requestId.current, category, message: message.trim() }, userId);
      trackEvent('feedback_submitted', { member: !!userId, category });
      setReceived(true);
      // The form disappears on success, so move focus to the remaining action.
      window.requestAnimationFrame(() => dialog.current?.querySelector<HTMLButtonElement>('.feedback-done')?.focus());
    } catch (reason) {
      setError(reason instanceof UsageError ? reason.message : reason instanceof Error && reason.message === 'AUTH_REQUIRED'
        ? '로그인이 만료되었습니다. 다시 로그인한 뒤 보내 주세요.'
        : '접수하지 못했습니다. 입력 내용은 유지되어 있으니 다시 시도해 주세요.');
    } finally { pending.current = false; setBusy(false); }
  };
  return createPortal(
    <div className="feedback-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div className="feedback-dialog" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} aria-busy={busy}>
        <button className="feedback-close" aria-label="피드백 창 닫기" disabled={busy} onClick={onClose}><X size={20} /></button>
        {received ? <>
          <div className="feedback-check"><Check size={26} /></div>
          <h2 id={titleId}>피드백을 접수했어요</h2>
          <p id={descriptionId}>보내주신 의견은 서비스 개선에 참고할게요.<br />소중한 의견 감사합니다.</p>
          <button className="feedback-submit feedback-done" onClick={onClose}>확인</button>
        </> : <form onSubmit={submit}>
          <h2 id={titleId}>피드백 남기기</h2>
          <p id={descriptionId}>불편했던 점이나 바라는 기능을 알려주세요.</p>
          <label htmlFor={`${titleId}-category`}>어떤 의견인가요?</label>
          <select id={`${titleId}-category`} value={category} disabled={busy} onChange={event => { changed(); setCategory(event.target.value as typeof category); }}>
            <option value="suggestion">개선 제안</option><option value="bug">오류 제보</option><option value="other">기타 의견</option>
          </select>
          <label htmlFor={`${titleId}-message`}>내용</label>
          <textarea id={`${titleId}-message`} className="feedback-message" value={message} disabled={busy} maxLength={2000} rows={5}
            placeholder="어떤 상황에서 불편했는지 자세히 알려주세요. (5자 이상)"
            onChange={event => { changed(); setMessage(event.target.value); }} aria-describedby={`${titleId}-notice`} />
          <div className="feedback-count">{message.length.toLocaleString()} / 2,000</div>
          <p className="feedback-notice" id={`${titleId}-notice`}>개인정보나 현장 기밀은 적지 마세요. 대화 내용은 자동으로 첨부되지 않습니다. 개별 답변은 제공하지 않으며, 접수 내용은 개선 검토를 위해 90일간 보관합니다. <a href="/privacy" target="_blank" rel="noopener noreferrer">개인정보처리방침</a></p>
          <p className="feedback-notice">답변이 필요한 문의는 <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>로 보내 주세요.</p>
          {error && <p className="feedback-error" role="alert">{error}</p>}
          <button className="feedback-submit" type="submit" disabled={busy || message.trim().length < 5}>{busy ? '접수 중…' : '피드백 보내기'}</button>
        </form>}
      </div>
    </div>, document.body,
  );
}

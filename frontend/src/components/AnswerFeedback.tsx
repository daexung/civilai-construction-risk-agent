import React, { useId, useRef, useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { sendAnswerFeedback, UsageError } from '../api';
import { trackEvent } from '../analytics';
import { ChatResponse } from '../types';
import './AnswerFeedback.css';

const reasons = [{ id: 'amount', label: '견적 금액이 이상해요' }, { id: 'evidence', label: '품셈 근거가 부족해요' },
  { id: 'understanding', label: '질문을 잘못 이해했어요' }, { id: 'other', label: '기타' }];
export default function AnswerFeedback({ response, ordinal, userId, disabled, onSaved }: {
  response: ChatResponse; ordinal: number; userId?: string; disabled?: boolean;
  onSaved?: (answerId: string, value: NonNullable<ChatResponse['answer_rating']>) => void;
}) {
  const prefix = useId();
  const pending = useRef(false);
  const [saved, setSaved] = useState(response.answer_rating);
  const [expanded, setExpanded] = useState(false);
  const [reason, setReason] = useState(response.answer_rating?.reason ?? '');
  const [comment, setComment] = useState(response.answer_rating?.comment ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!response.answer_id || response.status === 'ERROR') return null;
  const submit = async (rating: 'good' | 'bad') => {
    if (pending.current || disabled || (rating === 'bad' && !reason)) return;
    pending.current = true; setBusy(true); setError('');
    const value = { rating, reason: rating === 'bad' ? reason : null, comment: rating === 'bad' ? comment.trim() : '' };
    try {
      await sendAnswerFeedback({ thread_id: response.thread_id, answer_id: response.answer_id!, rating,
        ...(rating === 'bad' ? { reason, comment: value.comment } : {}) }, userId);
      setSaved(value); setExpanded(false); onSaved?.(response.answer_id!, value);
      trackEvent('answer_rated', { member: !!userId, rating, ...(rating === 'bad' ? { reason } : {}) });
    } catch (failure) {
      setError(failure instanceof UsageError ? failure.message : failure instanceof Error && failure.message === 'AUTH_REQUIRED'
        ? '로그인이 만료되었습니다. 다시 로그인한 뒤 평가해 주세요.'
        : '평가를 저장하지 못했어요. 잠시 후 다시 시도해 주세요.');
    } finally { pending.current = false; setBusy(false); }
  };
  return <div className="answer-feedback" aria-busy={busy}>
    <div className="answer-feedback-row">
      {(ordinal - 1) % 3 === 0 && <span className="answer-feedback-prompt">이번 답변은 도움이 되었나요?</span>}
      <button type="button" className="action-btn answer-rating" aria-label="도움됐어요" title="도움됐어요 · 평가 시 이 질문과 답변도 전송됩니다"
        aria-pressed={saved?.rating === 'good'} disabled={busy || disabled} onClick={() => { if (saved?.rating !== 'good') void submit('good'); }}><ThumbsUp size={16} strokeWidth={1.75} /></button>
      <button type="button" className="action-btn answer-rating" aria-label="아쉬워요" title="아쉬워요" aria-pressed={saved?.rating === 'bad'}
        aria-expanded={expanded} aria-controls={`${prefix}-form`} disabled={busy || disabled} onClick={() => { setExpanded(!expanded); setError(''); }}><ThumbsDown size={16} strokeWidth={1.75} /></button>
      <span className="answer-feedback-status" role="status">{busy ? '저장 중…' : saved ? '의견 감사합니다' : ''}</span>
    </div>
    <p className="answer-feedback-notice">평가 시 이 질문·답변도 개선 검토용으로 전송돼요. <a href="/privacy" target="_blank" rel="noopener noreferrer">처리방침</a></p>
    {expanded && <form id={`${prefix}-form`} className="answer-feedback-form" onSubmit={event => { event.preventDefault(); void submit('bad'); }}>
      <fieldset disabled={busy || disabled}><legend>어떤 점이 아쉬웠나요?</legend>
        <div className="answer-feedback-reasons">{reasons.map(item => <label key={item.id} className={reason === item.id ? 'selected' : ''}>
          <input type="radio" name={`${prefix}-reason`} value={item.id} checked={reason === item.id} onChange={() => setReason(item.id)} />{item.label}</label>)}</div>
        <label htmlFor={`${prefix}-comment`}>추가 의견 (선택)</label>
        <textarea id={`${prefix}-comment`} value={comment} onChange={event => setComment(event.target.value)} maxLength={1000} rows={3} placeholder="개인정보나 현장 기밀은 적지 마세요." />
        <div className="answer-feedback-form-actions"><button type="button" onClick={() => setExpanded(false)}>취소</button><button type="submit" disabled={!reason}>{busy ? '저장 중…' : '의견 보내기'}</button></div>
      </fieldset>
    </form>}
    {error && <p className="answer-feedback-error" role="alert">{error}</p>}
  </div>;
}

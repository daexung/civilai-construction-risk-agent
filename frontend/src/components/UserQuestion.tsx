import { useState } from 'react';
import { Pencil, RotateCcw } from 'lucide-react';

export default function UserQuestion({ text, disabled, onResend, failed, onRetry }: {
  text: string; disabled: boolean; onResend?: (text: string) => void; failed?: boolean; onRetry?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const cancel = () => { setDraft(text); setEditing(false); };
  const submit = () => {
    if (disabled || !draft.trim() || !onResend) return;
    onResend(draft.trim());
    setEditing(false);
  };
  return <div className="user-msg-wrap">
    {editing ? <div className="user-question-editor">
      <textarea autoFocus aria-label="질문 편집" maxLength={10000} rows={3} value={draft} disabled={disabled}
        onChange={event => setDraft(event.target.value)} onKeyDown={event => {
          if (event.key === 'Escape') cancel();
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
            event.preventDefault(); submit();
          }
        }} />
      <p>원래 기록은 유지돼요. 다시 요청하면 이용 횟수 1회가 차감돼요.</p>
      <div className="user-question-edit-actions">
        <button type="button" onClick={cancel}>취소</button>
        <button type="button" disabled={disabled || !draft.trim()} onClick={submit}>수정해서 다시 보내기</button>
      </div>
    </div> : <>
      <div className="user-bubble">{text}</div>
      {failed && <p className="user-question-failed">답변을 받지 못했어요.
        {onRetry && <button type="button" disabled={disabled} onClick={onRetry}>다시 시도</button>}</p>}
      {onResend && <div className="user-question-actions">
        {!failed && <button type="button" disabled={disabled} aria-label="질문 다시 보내기" title="다시 보내기 · 이용 횟수 1회 차감" onClick={() => onResend(text)}><RotateCcw size={16} strokeWidth={1.75} /></button>}
        <button type="button" disabled={disabled} aria-label="질문 편집하기" title="질문 편집" onClick={() => { setDraft(text); setEditing(true); }}><Pencil size={16} strokeWidth={1.75} /></button>
      </div>}
    </>}
  </div>;
}

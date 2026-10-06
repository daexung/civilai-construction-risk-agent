import React, { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import useDialogFocus from './useDialogFocus';
import './DeleteConversationDialog.css';

interface Props { title: string; busy: boolean; error: string; onClose: () => void; onDelete: () => void; }
export default function DeleteConversationDialog({ title, busy, error, onClose, onDelete }: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose, busy, '.delete-dialog-cancel');
  return createPortal(<div className="delete-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <div className="delete-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} aria-busy={busy} tabIndex={-1}>
      <h2 id={titleId}>대화를 삭제할까요?</h2>
      <p className="delete-dialog-title">{title}</p>
      <p id={descriptionId}>대화 내용과 계산 기록이 삭제되며, 복원할 수 없습니다.</p>
      {error && <p className="delete-dialog-error" role="alert">{error}</p>}
      <div className="delete-dialog-actions">
        <button className="delete-dialog-cancel" disabled={busy} onClick={onClose}>취소</button>
        <button className="delete-dialog-confirm" disabled={busy} onClick={onDelete}>{busy ? '삭제 중…' : '삭제'}</button>
      </div>
    </div>
  </div>, document.body);
}

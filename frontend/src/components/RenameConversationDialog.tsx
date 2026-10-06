import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import useDialogFocus from './useDialogFocus';
import './DeleteConversationDialog.css';

interface Props { title: string; busy: boolean; error: string; onClose: () => void; onSave: (title: string) => void; }
export default function RenameConversationDialog({ title, busy, error, onClose, onSave }: Props) {
  const titleId = useId();
  const inputId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState(title.slice(0, 200));
  useDialogFocus(dialog, onClose, busy, 'input');
  const normalized = value.replace(/\s+/g, ' ').trim();
  return createPortal(<div className="delete-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <div className="delete-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy} tabIndex={-1}>
      <h2 id={titleId}>대화 이름 바꾸기</h2>
      <form onSubmit={event => { event.preventDefault(); if (!busy && normalized) onSave(normalized); }}>
        <label className="rename-dialog-label" htmlFor={inputId}>대화 이름</label>
        <input id={inputId} className="rename-dialog-input" value={value} maxLength={200} disabled={busy}
          onChange={event => setValue(event.target.value)} onFocus={event => event.target.select()} autoComplete="off" />
        {error && <p className="delete-dialog-error" role="alert">{error}</p>}
        <div className="delete-dialog-actions">
          <button type="button" className="delete-dialog-cancel" disabled={busy} onClick={onClose}>취소</button>
          <button type="submit" className="rename-dialog-save" disabled={busy || !normalized}>{busy ? '저장 중…' : '저장'}</button>
        </div>
      </form>
    </div>
  </div>, document.body);
}

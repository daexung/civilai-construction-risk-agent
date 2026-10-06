import React, { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import './LoginDialog.css';
import useDialogFocus from './useDialogFocus';

interface Props { busy: boolean; error: string; onClose: () => void; onGoogleLogin: () => void; }

export default function LoginDialog({ busy, error, onClose, onGoogleLogin }: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose, busy, '.login-dialog-google');

  return createPortal(
    <div className="login-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div className="login-dialog" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} aria-busy={busy}>
        <button className="login-dialog-close" type="button" aria-label="로그인 창 닫기" disabled={busy} onClick={onClose}><X size={19} strokeWidth={1.75} /></button>
        <h2 id={titleId}>품셈이</h2>
        <p className="login-dialog-description" id={descriptionId}>공사비 견적부터 품셈 상담까지,<br />품셈이와 함께 쉽고 간편하게.</p>
        <button className="login-dialog-google" type="button" disabled={busy} onClick={onGoogleLogin}>
          <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
            <path fill="#FBBC05" d="M10.53 28.59A14.41 14.41 0 0 1 9.75 24c0-1.59.27-3.13.76-4.59l-7.98-6.19A23.87 23.87 0 0 0 0 24c0 3.87.93 7.53 2.56 10.78l7.97-6.19z" />
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.91-5.8l-7.73-6c-2.15 1.45-4.92 2.3-8.18 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
          </svg>
          <span>{busy ? '로그인 확인 중…' : 'Google로 로그인'}</span>
        </button>
        {error && <p className="login-dialog-error" role="alert">{error}</p>}
        <p className="login-dialog-terms">로그인하면 <a href="/terms" target="_blank" rel="noopener noreferrer">이용약관</a>이 적용됩니다.</p>
      </div>
    </div>, document.body,
  );
}

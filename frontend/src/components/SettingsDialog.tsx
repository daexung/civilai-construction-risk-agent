import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { LogOut, Settings, UserRound, X } from 'lucide-react';
import useDialogFocus from './useDialogFocus';
import './SettingsDialog.css';
import { UsageStatus } from '../types';
import UsageSummary from './UsageSummary';
import { analyticsAllowed, setAnalyticsAllowed } from '../analytics';

interface Props {
  usage?: UsageStatus | null;
  accountName: string | null;
  accountEmail: string | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onLogin: () => void;
  onLogout: () => void;
  onDeleteAccount?: () => void;
}

export default function SettingsDialog({ usage, accountName, accountEmail, busy, error, onClose, onLogin, onLogout, onDeleteAccount }: Props) {
  const [tab, setTab] = useState<'general' | 'account'>(accountName ? 'account' : 'general');
  const id = useId();
  const [analyticsEnabled, setAnalyticsEnabled] = useState(analyticsAllowed);
  const dialog = useRef<HTMLDivElement>(null);
  useDialogFocus(dialog, onClose, busy, '.settings-dialog-close');
  return createPortal(
    <div className="settings-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div className="settings-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1} aria-busy={busy}>
        <header><h2 id={`${id}-title`}>설정</h2><button className="settings-dialog-close" aria-label="설정 닫기" disabled={busy} onClick={onClose}><X size={20} strokeWidth={1.75} /></button></header>
        <div className="settings-body">
          <nav aria-label="설정 메뉴">
            <button aria-current={tab === 'general' ? 'page' : undefined} onClick={() => setTab('general')}><Settings size={18} strokeWidth={1.75} />일반</button>
            <button aria-current={tab === 'account' ? 'page' : undefined} onClick={() => setTab('account')}><UserRound size={18} strokeWidth={1.75} />계정</button>
          </nav>
          <section aria-label={tab === 'general' ? '일반 설정' : '계정 설정'}>
            <h3>{tab === 'general' ? '일반' : '계정'}</h3>
            {tab === 'general' ? <>
              <div className="settings-row"><span>언어</span><span className="settings-value">한국어</span></div>
              <div className="settings-row"><div><span>방문·기능 사용 통계</span><p>질문·답변 본문과 계정 정보는 보내지 않아요.</p></div><input type="checkbox" aria-label="방문·기능 사용 통계 허용" checked={analyticsEnabled} onChange={event => { setAnalyticsEnabled(event.target.checked); setAnalyticsAllowed(event.target.checked); }} /></div>
              <div className="settings-row"><span>이용약관</span><a href="/terms" target="_blank" rel="noopener noreferrer">보기</a></div>
              <div className="settings-row"><span>개인정보 처리방침</span><a href="/privacy" target="_blank" rel="noopener noreferrer">보기</a></div>
            </> : accountName ? <>
              <div className="settings-identity"><span className="chat-account-avatar" aria-hidden="true">{accountName.slice(0, 1).toUpperCase()}</span><div><strong>{accountName}</strong><span>{accountEmail}</span></div></div>
              <div className="settings-row"><span>로그인 방식</span><span className="settings-value">Google</span></div>
              <div className="settings-row settings-usage"><UsageSummary usage={usage} /></div>
              <div className="settings-row"><div><span>로그아웃</span><p>이 기기에서 로그아웃합니다.</p></div><button className="settings-logout" disabled={busy} onClick={onLogout}><LogOut size={16} strokeWidth={1.75} />{busy ? '로그아웃 중…' : '로그아웃'}</button></div>
              <div className="settings-row"><div><span>회원탈퇴</span><p>계정과 저장된 대화를 삭제합니다.</p></div><button className="settings-logout settings-delete-account" disabled={busy} onClick={onDeleteAccount}>회원탈퇴</button></div>
            </> : <div className="settings-guest"><p>로그인하지 않은 상태입니다.</p><UsageSummary usage={usage} /><button onClick={onLogin}>로그인</button></div>}
            {error && <p className="settings-error" role="alert">{error}</p>}
          </section>
        </div>
      </div>
    </div>, document.body,
  );
}

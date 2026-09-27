import React, { useState, useRef, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { User } from '../types';
import { Settings, applyTheme } from '../settings';
import './UserMenu.css';

interface Props {
  user: User;
  onLogout: () => void;
  settings: Settings;
  onSettingsChange: (s: Settings) => void;
}

function ProfileModal({ user, onClose }: { user: User; onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const fields = [
    { label: '이름',  value: user.name },
    { label: '직급',  value: user.role === 'admin' ? '관리자' : '일반사원' },
    { label: '소속',  value: '공무팀' },
    { label: '이메일', value: user.email },
    { label: '권한',  value: user.role === 'admin' ? '시스템 관리자' : '일반 사용자' },
  ];

  return ReactDOM.createPortal(
    <div className="um-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="um-modal">
        <div className="um-modal-header">
          <h2 className="um-modal-title">내 정보</h2>
          <button className="um-modal-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="um-avatar-section">
          <div className="um-big-avatar">{user.name[0]}</div>
          <div className="um-avatar-name">{user.name}</div>
        </div>

        <div className="um-fields">
          {fields.map(({ label, value }) => (
            <div key={label} className="um-field">
              <span className="um-label">{label}</span>
              <span className="um-value">{value}</span>
            </div>
          ))}
        </div>

        <p className="um-notice">계정 정보는 관리자 시스템에서 관리됩니다.</p>
      </div>
    </div>,
    document.body
  );
}

function SettingsModal({
  settings, onSettingsChange, onClose,
}: {
  settings: Settings;
  onSettingsChange: (s: Settings) => void;
  onClose: () => void;
}) {
  const [local, setLocal] = useState<Settings>(settings);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleChange = (key: keyof Settings, value: string) => {
    const next = { ...local, [key]: value } as Settings;
    setLocal(next);
    if (key === 'theme') applyTheme(next.theme);
  };

  const handleSave = () => {
    onSettingsChange(local);
    onClose();
  };

  const rows = [
    { label: '응답 상세도',    key: 'detail' as const, opts: ['간략', '기본', '상세'] },
    { label: '금액 표시 단위', key: 'unit'   as const, opts: ['원', '천원', '만원'] },
    { label: '테마',          key: 'theme'  as const, opts: ['라이트', '다크'] },
  ];

  return ReactDOM.createPortal(
    <div className="um-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="um-modal">
        <div className="um-modal-header">
          <h2 className="um-modal-title">설정</h2>
          <button className="um-modal-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div className="um-fields">
          {rows.map(({ label, key, opts }) => (
            <div key={key} className="um-setting-row">
              <span className="um-label">{label}</span>
              <select
                className="um-select"
                value={local[key]}
                onChange={e => handleChange(key, e.target.value)}
              >
                {opts.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
          ))}
        </div>

        <button className="um-save-btn" onClick={handleSave}>저장</button>
      </div>
    </div>,
    document.body
  );
}

export default function UserMenu({ user, onLogout, settings, onSettingsChange }: Props) {
  const [menuOpen,      setMenuOpen]      = useState(false);
  const [showProfile,   setShowProfile]   = useState(false);
  const [showSettings,  setShowSettings]  = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node))
        setMenuOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  return (
    <>
      <div className="sidebar-footer" ref={containerRef}>
        <div
          className="user-info user-info-btn"
          role="button"
          tabIndex={0}
          onClick={() => setMenuOpen(v => !v)}
          onKeyDown={e => e.key === 'Enter' && setMenuOpen(v => !v)}
        >
          <div className="user-avatar">{user.name[0]}</div>
          <div className="user-detail">
            <span className="user-name">{user.name}</span>
            <span className="user-role">{user.role === 'admin' ? '관리자' : '일반사원'}</span>
          </div>
        </div>

        <button className="logout-btn" onClick={onLogout} title="로그아웃">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </button>

        {menuOpen && (
          <div className="user-dropdown">
            <button className="user-dropdown-item"
              onClick={() => { setMenuOpen(false); setShowProfile(true); }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              내 정보
            </button>
            <button className="user-dropdown-item"
              onClick={() => { setMenuOpen(false); setShowSettings(true); }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
              설정
            </button>
          </div>
        )}
      </div>

      {showProfile  && <ProfileModal user={user} onClose={() => setShowProfile(false)} />}
      {showSettings && (
        <SettingsModal
          settings={settings}
          onSettingsChange={onSettingsChange}
          onClose={() => setShowSettings(false)}
        />
      )}
    </>
  );
}

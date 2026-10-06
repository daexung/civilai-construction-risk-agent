import React, { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, LogOut } from 'lucide-react';
import { UsageStatus } from '../types';
import UsageSummary from './UsageSummary';

interface Props { name: string; usage?: UsageStatus | null; busy?: boolean; error?: string; onLogout?: () => void; }

export default function AccountMenu({ name, usage, busy, error, onLogout }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => { if (!wrapper.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  return <div className="chat-account-wrapper" ref={wrapper} onBlur={event => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false);
  }}>
    <button className="chat-account" ref={trigger} onClick={() => setOpen(value => !value)} aria-label="계정 메뉴 열기" aria-expanded={open} aria-controls={open ? id : undefined}>
      <span className="chat-account-avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <span className="chat-account-name">{name}</span>
      <ChevronDown className={open ? 'chat-account-chevron is-open' : 'chat-account-chevron'} size={16} strokeWidth={1.75} />
    </button>
    {open && <div id={id} className="chat-account-menu" role="region" aria-label="계정 메뉴">
      <UsageSummary usage={usage} />
      <button className="chat-account-logout" disabled={busy} onClick={onLogout}><LogOut size={17} strokeWidth={1.75} />{busy ? '로그아웃 중…' : '로그아웃'}</button>
      {error && <p className="settings-error" role="alert">{error}</p>}
    </div>}
  </div>;
}

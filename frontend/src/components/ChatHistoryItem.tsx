import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { EllipsisVertical, Trash2 } from 'lucide-react';

interface Props { id: string; title: string; active: boolean; disabled: boolean; onSelect: () => void; onDelete: () => void; }
export default function ChatHistoryItem({ title, active, disabled, onSelect, onDelete }: Props) {
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!position) return;
    menu.current?.querySelector('button')?.focus();
    const outside = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(null);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setPosition(null); trigger.current?.focus(); }
    };
    const close = () => setPosition(null);
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape, true);
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('mousedown', outside);
      document.removeEventListener('keydown', escape, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [position]);
  useEffect(() => { if (disabled) setPosition(null); }, [disabled]);
  return <div className={`chat-history-row${active ? ' chat-history-active' : ''}`}>
    <button className="chat-history-select" title={title} aria-current={active ? 'page' : undefined} disabled={disabled} onClick={onSelect}><span>{title}</span></button>
    <button ref={trigger} className="chat-history-more" aria-label={`${title} 대화 메뉴`} aria-haspopup="menu" aria-expanded={!!position} disabled={disabled}
      onClick={() => {
        const rect = trigger.current!.getBoundingClientRect();
        setPosition(position ? null : { left: Math.max(8, rect.right - 148), top: Math.min(rect.bottom + 4, window.innerHeight - 64) });
      }}><EllipsisVertical size={17} strokeWidth={1.75} aria-hidden="true" /></button>
    {position && createPortal(<div ref={menu} className="chat-history-menu" role="menu" aria-label="대화 작업" style={position}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setPosition(null); }}>
      <button role="menuitem" onClick={() => { setPosition(null); trigger.current?.focus(); onDelete(); }}><Trash2 size={16} aria-hidden="true" />삭제</button>
    </div>, document.body)}
  </div>;
}

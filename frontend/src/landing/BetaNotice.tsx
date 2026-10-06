import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowRight, X } from 'lucide-react';
import useDialogFocus from '../components/useDialogFocus';
import './BetaNotice.css';

const storageKey = 'poomsemi.betaNotice.hiddenDay';
type NoticeProps = { onStart: () => void; variant?: 'landing' | 'chat'; onFeedback?: () => void };
const koreaDay = () => new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);

function NoticeDialog({ onClose, onStart, variant = 'landing', onFeedback }: NoticeProps & { onClose: (hideToday: boolean) => void }) {
  const isChat = variant === 'chat';
  const [hideToday, setHideToday] = useState(false);
  const titleId = useId();
  const descriptionId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const close = () => onClose(hideToday);
  useDialogFocus(dialog, close, false, '.beta-notice-title', isChat ? '.app' : '.civil-landing');

  return createPortal(<div className="beta-notice-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <div className="beta-notice" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
      <button className="beta-notice-close" type="button" aria-label="베타 안내 닫기" onClick={close}><X size={20} strokeWidth={1.75} /></button>
      <span className="beta-notice-badge">OPEN BETA</span>
      <h2 id={titleId} className="beta-notice-title" tabIndex={-1}>{isChat ? <>함께 만드는<br />품셈이 베타 테스트</> : <>품셈이, 지금 무료로<br />경험해 보세요.</>}</h2>
      <p className="beta-notice-description" id={descriptionId}>현재 베타 테스트 기간으로,<br />공사비 견적과 품셈 상담을 무료로 이용할 수 있어요.</p>
      <p className="beta-notice-scope"><strong>최대 3개 공종을 한 견적서로 묶을 수 있어요</strong><br />공종과 물량을 쉼표로 나눠 적으면 공종별로 계산한 뒤 간접비는 한 번만 넣어 견적서를 만들어요. 지원 공종과 범위는 추후 업데이트할 예정이에요.</p>
      <p className="beta-notice-feedback">아직 베타 테스트 중이라 답변이나 견적 결과가 부족하거나 정확하지 않을 수 있어요. 이용해 보시고 불편한 점이나 개선 의견을 남겨 주세요.</p>
      {isChat && <p className="beta-notice-feedback-guide">왼쪽 메뉴의 ‘피드백 남기기’로 의견을 보내주시면 서비스 개선에 큰 도움이 됩니다.</p>}
      {!isChat && <><div className="beta-notice-limits">
        <div><span>가입 없이 가볍게</span><strong>하루 <b>5</b>회 무료</strong></div>
        <div className="beta-notice-member"><span>Google로 가입하면</span><strong>하루 <b>20</b>회 무료</strong><small>대화 저장과 이어서 견적까지</small></div>
      </div>
      <p className="beta-notice-note">사용량은 매일 자정(한국 시간)에 초기화됩니다.<br />전체 서비스의 하루 이용 한도에 도달하면 다음 날 이용할 수 있어요.</p></>}
      <button className="beta-notice-start" type="button" onClick={() => { close(); onStart(); }}>{isChat ? '확인하고 대화 시작하기' : '무료로 시작하기'} <ArrowRight size={18} /></button>
      {isChat && onFeedback && <button className="beta-notice-feedback-action" type="button" onClick={() => { close(); onFeedback(); }}>피드백 남기기</button>}
      <p className="beta-notice-disclaimer">베타 기간 중 기능과 이용 한도는 변경될 수 있어요.<br />견적 결과는 참고용 초안으로 확인해 주세요.</p>
      <div className="beta-notice-footer"><label><input type="checkbox" checked={hideToday} onChange={event => setHideToday(event.target.checked)} />오늘 하루 보지 않기</label></div>
    </div>
  </div>, document.body);
}

export default function BetaNotice({ onStart, variant = 'landing', onFeedback }: NoticeProps) {
  const hiddenKey = variant === 'chat' ? 'poomsemi.chatBetaNotice.hiddenDay' : storageKey;
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(hiddenKey) !== koreaDay(); } catch { return true; }
  });
  const close = (hideToday: boolean) => {
    if (hideToday) { try { localStorage.setItem(hiddenKey, koreaDay()); } catch { /* Storage may be blocked; closing still works. */ } }
    setOpen(false);
  };
  return open ? <NoticeDialog onClose={close} onStart={onStart} variant={variant} onFeedback={onFeedback} /> : null;
}

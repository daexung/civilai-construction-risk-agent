import React, { useEffect, useRef } from 'react';
import LandingPreview from './LandingPreview';
import BetaNotice from './BetaNotice';
import { CONTACT_EMAIL } from '../contact';
import demo from './demo.json';
import './Landing.css';

function Reveal({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (!window.IntersectionObserver) { element.classList.add('in'); return; }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        element.classList.add('in');
        observer.disconnect();
      }
    }, { threshold: 0.15 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return <div ref={ref} className="lp-reveal">{children}</div>;
}

const steps = [
  ['공종과 물량 입력', '계산할 작업과 물량을 평소 쓰는 말로 설명합니다. 부족한 조건은 이어서 확인합니다.'],
  ['품셈 근거로 견적 계산', '해당 품셈을 찾고 작업 조건과 적용 단가를 반영해 원가계산서를 정리합니다.'],
  ['내역과 원문 확인', '도급액, 일위대가, 산출근거를 확인하고 계산 결과를 엑셀로 내려받습니다.'],
];
const features = [
  { color: 'estimate', title: '공사비 견적', description: '공종과 물량, 작업 조건을 바탕으로 공사비를 계산합니다. 미산정 항목은 결과에서 구분합니다.', label: '견적 내역', sample: '원가계산서 · 일위대가 · 산출근거' },
  { color: 'consult', title: '품셈 상담', description: '품셈 적용 기준과 규정에 관한 질문에 관련 원문 근거를 찾아 답합니다.', label: '원문 확인', sample: '품셈 절 번호 · 원문 페이지 · 근거 내용' },
  { color: 'export', title: '엑셀 출력', description: '원가계산서와 일위대가, 산출근거를 시트별로 정리해 실무에서 확인할 수 있도록 제공합니다.', label: '다운로드', sample: '견적 결과 .xlsx' },
];

interface Props { onStart: () => void; onExample: (question: string) => void; }

export default function Landing({ onStart, onExample }: Props) {
  const start = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onStart();
  };
  return <div className="civil-landing">
    <BetaNotice onStart={onStart} />
    <div id="top" />
    <a className="lp-skip" href="#landing-main">본문으로 건너뛰기</a>
    <header className="lp-header">
      <div className="lp-container lp-header-inner">
        <a className="lp-wordmark" href="#top" aria-label="품셈이 홈">품셈이</a>
        <nav aria-label="주 메뉴">
          <a className="lp-button lp-nav-demo" href="/chat" onClick={start}>시작하기</a>
        </nav>
      </div>
    </header>
    <main id="landing-main">
      <section className="lp-container lp-hero" aria-labelledby="landing-title">
        <p className="lp-eyebrow">표준품셈 AI 에이전트</p>
        <h1 id="landing-title">공사비 견적,<br />쉽고 간편하게.</h1>
        <p className="lp-hero-description">필요한 공사를 설명해 주세요. 견적부터 품셈 근거까지 한 번에 확인할 수 있습니다.</p>
        <div className="lp-actions">
          <a className="lp-button" href="#demo">견적 예시 보기</a>
          <a className="lp-text-link" href="#features">어떤 기능이 있나요? <span aria-hidden="true">→</span></a>
        </div>
        <div id="demo" className="lp-demo lp-report">
          <div className="lp-report-toolbar">
            <span>품셈AI · 견적 예시</span>
            <span>{demo.response.status === 'PARTIAL' ? '부분 금액 계산' : '금액 계산 완료'}</span>
          </div>
          <div className="lp-live-preview-grid">
            <div className="lp-question">
              <p className="lp-label">질문</p>
              <p className="lp-question-text">{demo.question}</p>
              <p className="lp-label lp-tools-label">확인할 결과</p>
              <ul className="lp-tools">
                <li className="lp-estimate"><span aria-hidden="true" />공사비 견적 계산</li>
                <li className="lp-consult"><span aria-hidden="true" />일위대가·품셈 원문 확인</li>
              </ul>
            </div>
            <LandingPreview />
          </div>
          <p className="lp-report-note">저장된 실제 응답이며 미산정 항목이 포함되어 있습니다. <button type="button" className="lp-example-button" onClick={() => onExample(demo.question)}>이 질문으로 견적 시작하기 <span aria-hidden="true">→</span></button></p>
        </div>
      </section>
      <section className="lp-how" aria-labelledby="landing-how-title">
        <div className="lp-container">
          <Reveal><h2 id="landing-how-title">작업을 설명하면,<br />필요한 계산이 이어집니다.</h2></Reveal>
          <ol className="lp-steps">
            {steps.map(([title, description], index) => <li key={title}><Reveal><div className="lp-step">
              <span className="lp-step-number">0{index + 1}</span><h3>{title}</h3><p>{description}</p>
            </div></Reveal></li>)}
          </ol>
        </div>
      </section>
      <section className="lp-container lp-features" id="features" aria-labelledby="landing-features-title">
        <Reveal><p className="lp-eyebrow">기능 소개</p><h2 id="landing-features-title">세 가지 기능을 질문 하나로.</h2></Reveal>
        <div className="lp-feature-list">
          {features.map(feature => <Reveal key={feature.title}><article className={`lp-feature lp-${feature.color}`}>
            <h3><i aria-hidden="true" />{feature.title}</h3>
            <p>{feature.description}</p>
            <div className="lp-feature-sample"><span>{feature.label}</span><p>{feature.sample}</p></div>
          </article></Reveal>)}
        </div>
      </section>
      <section className="lp-basis" aria-labelledby="landing-basis-title">
        <div className="lp-container"><Reveal>
          <h2 id="landing-basis-title">금액과 함께,<br />품셈의 근거도.</h2>
          <p className="lp-basis-description">적용 조건과 단가, 산출 과정, 품셈 원문을 함께 확인하세요.</p>
          <div className="lp-final-cta">
            <p>품셈이에 지금 바로 물어보세요.</p>
            <a className="lp-button lp-button-white" href="/chat" onClick={start}>견적·상담 시작하기</a>
          </div>
        </Reveal></div>
      </section>
    </main>
    <footer className="lp-container lp-footer lp-landing-footer">
      <div className="lp-footer-top"><span className="lp-footer-brand">품셈이</span><div className="lp-footer-links"><a href="/terms">이용약관</a><a href="/privacy">개인정보 처리방침</a></div></div>
      <p className="lp-footer-contact">문의: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></p>
    </footer>
  </div>;
}

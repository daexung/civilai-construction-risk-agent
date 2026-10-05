import React, { useEffect, useId, useState } from 'react';
import { EXAMPLE_QUESTIONS } from '../examples';
import { ChatResponse, ComputedResult } from '../types';
import { conditionSummary } from '../components/StatementView';
import demo from './demo.json';
import './Landing.css';

interface Props {
  onStart: () => void;
  onExample: (question: string) => void;
}

const demoResponse = demo.response as unknown as ChatResponse;
const demoResult = demoResponse.result as ComputedResult;
const demoAmount = demoResponse.tables.statement_rows.find((row) => row.name === '도급액');
const previewRows = demoResponse.tables.statement_rows.filter((row) =>
  ['재료비', '노무비 계', '경비 계', '일반관리비', '이윤', '부가가치세'].includes(row.name));
const previewTabs = ['원가계산서', '일위대가', '산출근거'];

function formatAmount(value: number | string | null | undefined): string {
  return value == null ? '—' : Number(value).toLocaleString('ko-KR');
}

function LandingPreview() {
  const [selected, setSelected] = useState(0);
  const prefix = useId();
  const source = demoResult.daily_volume?.citations[0];
  const activateTab = (index: number) => {
    setSelected(index);
    document.getElementById(`${prefix}-tab-${index}`)?.focus();
  };
  return (
    <div className="landing-preview-frame" aria-label="실제 견적 답변 미리보기">
      <p className="preview-question">{demo.question}</p>
      <div className="preview-result">
        <div className="preview-result-heading">
          <span className="preview-kind"><span className="evidence-dot" />견적</span>
          <span className="preview-status">{demoResponse.status === 'PARTIAL' ? '부분 금액 계산' : '금액 계산 완료'}</span>
        </div>
        <div className="preview-amount">
          <span>도급액</span>
          <strong>{formatAmount(demoAmount?.amount)}<small>원</small></strong>
          <p>부가세 포함 · 표준품셈 기준 참고 금액</p>
        </div>
        <p className="preview-conditions">기준: {conditionSummary(demoResponse.conditions)}</p>
        <div className="preview-tabs" role="tablist" aria-label="견적 결과">
          {previewTabs.map((label, index) => <button key={label} type="button" role="tab"
            id={`${prefix}-tab-${index}`} aria-selected={selected === index}
            aria-controls={`${prefix}-panel`} tabIndex={selected === index ? 0 : -1}
            onClick={() => setSelected(index)} onKeyDown={(event) => {
              const next = event.key === 'ArrowRight' ? (index + 1) % previewTabs.length
                : event.key === 'ArrowLeft' ? (index + previewTabs.length - 1) % previewTabs.length
                  : event.key === 'Home' ? 0 : event.key === 'End' ? previewTabs.length - 1 : null;
              if (next != null) { event.preventDefault(); activateTab(next); }
            }}>{label}</button>)}
        </div>
        <div className="preview-tab-panel" role="tabpanel" id={`${prefix}-panel`}
          aria-labelledby={`${prefix}-tab-${selected}`} tabIndex={0}>
          {selected === 0 && <dl className="preview-costs">
            {previewRows.map((row) => <div key={row.name}><dt>{row.name}</dt><dd>{formatAmount(row.amount)}원</dd></div>)}
          </dl>}
          {selected === 1 && <div className="preview-unit-table-wrap"><table className="preview-unit-table">
            <caption>일위대가표 ({demoResult.unit_basis.per}당)</caption>
            <thead><tr><th>명칭</th><th>수량</th><th>단위</th></tr></thead>
            <tbody>{demoResult.unit_lines.map((line) => <tr key={line.name}>
              <td>{line.name}</td><td>{line.applied}</td><td>{line.unit}</td>
            </tr>)}</tbody>
          </table></div>}
          {selected === 2 && <div className="preview-basis">
            <span className="preview-source-page">p.{source?.pdf_page} · 원문 근거</span>
            <p>{source?.label}</p>
            <dl className="preview-costs">
              <div><dt>일당시공량</dt><dd>{demoResult.daily_volume?.value} {demoResult.daily_volume?.unit}</dd></div>
              <div><dt>작업조 투입량</dt><dd>{demoResult.work_days?.value} 작업조·일</dd></div>
            </dl>
          </div>}
        </div>
        <div className="preview-unpriced">
          <strong>미산정 항목</strong>
          <p>{demoResponse.tables.statement_rows.filter((row) => row.status === '미산정').map((row) => row.name).join(' · ')}</p>
        </div>
      </div>
      {source && <button type="button" className="preview-source-link" onClick={() => activateTab(2)}>
        <FlowIcon kind="source" /><span>{source.section_no} {source.section_title}</span>
        <span className="preview-source-page">p.{source.pdf_page} · 원문 근거</span>
        <span aria-hidden="true">↗</span>
      </button>}
    </div>
  );
}

function FlowIcon({ kind }: { kind: string }) {
  const common = { width: 26, height: 26, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  if (kind === 'search') return <svg {...common}><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.2 4.2M8 10.8h5.6M10.8 8v5.6" /></svg>;
  if (kind === 'calculate') return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8 11h2m4 0h2m-8 4h2m4 0h2m-8 3h2m4 0h2" /></svg>;
  if (kind === 'source') return <svg {...common}><path d="M6 3.5h8l4 4V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" /><path d="M14 3.5V8h4M8 12h8M8 16h5" /></svg>;
  return <svg {...common}><path d="M4 12h15M13 6l6 6-6 6" /><circle cx="5" cy="12" r="2" /></svg>;
}

export default function Landing({ onStart, onExample }: Props) {
  useEffect(() => {
    const sections = Array.from(document.querySelectorAll<HTMLElement>('.landing-reveal'));
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) {
      sections.forEach((section) => section.classList.add('is-visible'));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  return (
    <main className="landing-page">
      <div className="landing-container">
        <header className="landing-header">
          <a className="landing-logo" href="/" onClick={(event) => { event.preventDefault(); window.history.pushState({}, '', '/'); window.dispatchEvent(new PopStateEvent('popstate')); }} aria-label="품셈AI 첫 페이지">품셈<span>AI</span></a>
          <button className="landing-start landing-start-small" onClick={onStart}>시작하기 <span aria-hidden="true">↗</span></button>
        </header>

        <div className="landing-intro">
          <section className="landing-hero landing-reveal">
            <p className="landing-eyebrow"><span className="evidence-dot" /> 2026 표준품셈을 근거로</p>
            <h1>품셈 찾고 계산하던 시간을,<br /><span>질문 한 줄로.</span></h1>
            <p className="landing-lead">2026 건설공사 표준품셈 원문을 근거로 공사비를 계산하고,<br className="desktop-break" /> 품셈 질문에 답합니다.</p>
            <div className="landing-hero-actions">
              <a className="landing-button landing-button-outline" href="#features">기능 보기 <span aria-hidden="true">↓</span></a>
              <button className="landing-button landing-button-primary" onClick={onStart}>지금 시작하기 <span aria-hidden="true">→</span></button>
            </div>
          </section>

          <section className="landing-demo landing-reveal" aria-label="견적 답변 미리보기">
            <div className="demo-window-top"><span /><span /><span /><p>품셈AI · 견적 답변</p><b>실제 응답</b></div>
            <LandingPreview />
          </section>
        </div>
        <div className="landing-facts" aria-label="표준품셈 자료">
          <span><strong>2026</strong> 표준품셈</span>
          <span><strong>5개</strong> 부문</span>
          <span><strong>1,058개</strong> 절</span>
          <span>근거 원문 첨부 <FlowIcon kind="source" /></span>
        </div>

        <section className="landing-features landing-reveal" id="features">
          <div className="section-heading">
            <p className="landing-eyebrow">질문 한 줄이면 됩니다</p>
            <h2>찾고, 계산하고, 확인하는 일을<br />한곳에서 이어가세요.</h2>
          </div>
          <div className="feature-grid">
            <div className="feature-copy">
              <article className="feature-copy-item">
                <span className="feature-kicker">01 · 견적</span>
                <h3>물량만 말하세요.<br />원가계산서는 AI가 씁니다.</h3>
                <p>표준품셈 근거를 확인하고, 조건에 맞춰 공사비를 계산합니다.</p>
              </article>
              <article className="feature-copy-item">
                <span className="feature-kicker">02 · 상담</span>
                <h3>품셈 규정이 헷갈릴 때,<br />원문으로 답합니다.</h3>
                <p>질문에 맞는 품셈 내용을 찾아 근거와 함께 보여줍니다.</p>
              </article>
              <article className="feature-copy-item">
                <span className="feature-kicker">03 · 엑셀</span>
                <h3>실무 양식 그대로<br />엑셀로 받으세요.</h3>
                <p>계산 결과와 산출 근거를 시트별로 정리해 내려받습니다.</p>
              </article>
            </div>
            <div className="feature-examples">
              <div className="mini-estimate-card">
                <span className="mini-kind">견적 미리보기</span>
                <p className="mini-question">{demo.question}</p>
                <div className="mini-answer-row"><span>도급액</span><strong>{demoResponse.tables.statement_rows.find((row) => row.name === '도급액')?.amount?.toLocaleString('ko-KR') ?? '—'}원</strong></div>
                <p className="mini-reference">부가세 포함 · 표준품셈 기준 참고 금액</p>
              </div>
              <div className="mini-qa-card">
                <span className="mini-kind">상담 미리보기</span>
                <p className="mini-question">진동기 안 쓰면 인원이 줄어?</p>
                <p className="mini-qa-answer">품셈의 작업 조건을 원문에서 확인해 답합니다.</p>
                <span className="mini-page-badge">p.186 · 원문 근거</span>
              </div>
              <div className="mini-excel-card">
                <span className="mini-kind">엑셀 미리보기</span>
                <div className="mini-sheet-tabs">{['견적서', '원가계산서', '내역서', '일위대가', '단가대비표', '산출근거'].map((tab) => <span key={tab}>{tab}</span>)}</div>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-process landing-reveal">
          <div className="section-heading section-heading-center">
            <p className="landing-eyebrow">질문에서 근거까지</p>
            <h2>이렇게 만듭니다.</h2>
          </div>
          <div className="process-steps">
            {[['질문 이해', 'interpret'], ['품셈 검색', 'search'], ['조건에 맞게 계산', 'calculate'], ['근거와 함께 답', 'source']].map(([label, icon], index) => (
              <div className="process-step" key={label}>
                <span className="process-number">0{index + 1}</span>
                <span className="process-icon"><FlowIcon kind={icon} /></span>
                <strong>{label}</strong>
                {index < 3 && <span className="process-arrow" aria-hidden="true">→</span>}
              </div>
            ))}
          </div>
        </section>

        <section className="landing-questions landing-reveal">
          <div className="section-heading section-heading-center">
            <p className="landing-eyebrow">어떤 질문부터 해볼까요?</p>
            <h2>예시 질문</h2>
          </div>
          <div className="question-grid">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button className="landing-question-card" key={example.text} onClick={() => onExample(example.text)}>
                <span className={`landing-question-kind ${example.kind === '견적' ? 'estimate' : 'qa'}`}>{example.kind}</span>
                <span>{example.text}</span>
                <span className="question-arrow" aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
        </section>

        <section className="landing-last-cta landing-reveal">
          <p className="landing-eyebrow">품셈AI와 시작해 보세요</p>
          <h2>지금 바로 물어보세요.</h2>
          <button className="landing-button landing-button-primary" onClick={onStart}>지금 시작하기 <span aria-hidden="true">→</span></button>
        </section>

        <footer className="landing-footer">
          <span className="landing-logo">품셈<span>AI</span></span>
          <p>표준품셈 기준 참고 금액 · 국토교통부와 무관</p>
        </footer>
      </div>
    </main>
  );
}

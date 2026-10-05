import React, { useId, useState } from 'react';
import { ChatResponse, ComputedResult } from '../types';
import { conditionSummary } from '../components/StatementView';
import demo from './demo.json';
import './Landing.css';

const demoResponse = demo.response as unknown as ChatResponse;
const demoResult = demoResponse.result as ComputedResult;
const statementRows = demoResponse.tables.statement_rows;
const demoAmount = statementRows.find(row => row.name === '도급액');
const previewRows = statementRows.filter(row =>
  ['재료비', '노무비 계', '경비 계', '일반관리비', '이윤', '부가가치세'].includes(row.name));
const previewTabs = ['원가계산서', '일위대가', '산출근거'];

function formatAmount(value: number | string | null | undefined): string {
  return value == null ? '—' : Number(value).toLocaleString('ko-KR');
}

function sumRows(names: string[]): number | null {
  const rows = names.map(name => statementRows.find(row => row.name === name));
  return rows.some(row => row?.amount == null) ? null
    : rows.reduce((total, row) => total + Number(row!.amount), 0);
}

const summaryRows = [
  { name: '재료·노무·경비', amount: sumRows(['재료비', '노무비 계', '경비 계']), color: 'estimate' },
  { name: '일반관리비·이윤', amount: sumRows(['일반관리비', '이윤']), color: 'consult' },
  { name: '부가가치세', amount: sumRows(['부가가치세']), color: 'export' },
];

function Chevron() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

export default function LandingPreview() {
  const [selected, setSelected] = useState(0);
  const [calculationOpen, setCalculationOpen] = useState(false);
  const [basisOpen, setBasisOpen] = useState(false);
  const prefix = useId();
  const source = demoResult.daily_volume?.citations[0];
  const activateTab = (index: number) => {
    setSelected(index);
    document.getElementById(`${prefix}-tab-${index}`)?.focus();
  };
  return <div className="landing-preview-frame" aria-label="실제 견적 답변 미리보기">
    <div className="preview-amount">
      <span>도급액</span>
      <strong>{formatAmount(demoAmount?.amount)}<small>원</small></strong>
      <p>부가세 포함 · {demoResponse.status === 'PARTIAL' ? '미산정 항목이 있는 참고 금액' : '표준품셈 기준 참고 금액'}</p>
    </div>
    <table className="preview-summary-table">
      <caption className="lp-sr-only">견적 요약 내역</caption>
      <tbody>
        {summaryRows.map(row => <tr key={row.name} className={`lp-${row.color}`}>
          <th scope="row"><span className="preview-category-mark" aria-hidden="true" />{row.name}</th>
          <td>{formatAmount(row.amount)}원</td>
        </tr>)}
        <tr className="preview-total"><th scope="row">합계</th><td>{formatAmount(demoAmount?.amount)}원</td></tr>
      </tbody>
    </table>
    <div className="preview-disclosures">
      <div className="preview-disclosure">
        <button type="button" aria-expanded={calculationOpen} aria-controls={`${prefix}-calculation`}
          onClick={() => setCalculationOpen(open => !open)}>계산 과정<Chevron /></button>
        <div className="preview-disclosure-content" id={`${prefix}-calculation`} hidden={!calculationOpen}>
          <div className="preview-tabs" role="tablist" aria-label="견적 결과">
            {previewTabs.map((label, index) => <button key={label} type="button" role="tab"
              id={`${prefix}-tab-${index}`} aria-selected={selected === index}
              aria-controls={`${prefix}-panel`} tabIndex={selected === index ? 0 : -1}
              onClick={() => setSelected(index)} onKeyDown={event => {
                const next = event.key === 'ArrowRight' ? (index + 1) % previewTabs.length
                  : event.key === 'ArrowLeft' ? (index + previewTabs.length - 1) % previewTabs.length
                    : event.key === 'Home' ? 0 : event.key === 'End' ? previewTabs.length - 1 : null;
                if (next != null) { event.preventDefault(); activateTab(next); }
              }}>{label}</button>)}
          </div>
          <div className="preview-tab-panel" role="tabpanel" id={`${prefix}-panel`}
            aria-labelledby={`${prefix}-tab-${selected}`} tabIndex={0}>
            {selected === 0 && <dl className="preview-costs">
              {previewRows.map(row => <div key={row.name}><dt>{row.name}</dt><dd>{formatAmount(row.amount)}원</dd></div>)}
            </dl>}
            {selected === 1 && <div className="preview-unit-table-wrap"><table className="preview-unit-table">
              <caption>일위대가표 ({demoResult.unit_basis.per}당)</caption>
              <thead><tr><th>명칭</th><th>수량</th><th>단위</th></tr></thead>
              <tbody>{demoResult.unit_lines.map(line => <tr key={line.name}>
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
        </div>
      </div>
      <div className="preview-disclosure">
        <button type="button" aria-expanded={basisOpen} aria-controls={`${prefix}-basis`}
          onClick={() => setBasisOpen(open => !open)}>적용 근거와 가정<Chevron /></button>
        <div className="preview-disclosure-content" id={`${prefix}-basis`} hidden={!basisOpen}>
          <p className="preview-conditions">기준: {conditionSummary(demoResponse.conditions)}</p>
          {source && <p className="preview-citation"><strong>{source.section_no} {source.section_title}</strong><br />{source.label}<br /><span className="preview-source-page">p.{source.pdf_page} · 원문 근거</span></p>}
          <div className="preview-unpriced">
            <strong>미산정 항목</strong>
            <p>{statementRows.filter(row => row.status === '미산정').map(row => row.name).join(' · ')}</p>
          </div>
        </div>
      </div>
    </div>
  </div>;
}

import React, { useId, createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUp, Check, ChevronDown, Copy, Download, MessageSquareText, PanelLeft, Plus, Settings } from 'lucide-react';
import { AgentQuestion, BlockedResult, ChatResponse, ChatTurn, ChoiceValue, Citation, ComputedResult, PricedResult } from '../types';
import { downloadEstimate } from '../api';
import { EXAMPLE_QUESTIONS } from '../examples';
import { showToast } from '../toast';
import { BillTable, ConditionsBar, RateTable, StatementTable } from './StatementView';
import './ChatArea.css';
import './ChatWorkspace.css';

interface Props {
  accountLabel?: string | null;
  authLoading?: boolean;
  onLogin?: () => void;
  onSettings?: () => void;
  conversations?: { id: string; title: string }[];
  activeConversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  turns: ChatTurn[];
  loading: boolean;
  onSendMessage: (text: string) => void;
  onSendAnswers: (answers: Record<string, ChoiceValue>, summary: string) => void;
  onChangeConditions: (turnId: string, conditions: Record<string, string>) => void;
  onNewChat: () => void;
  onSendExample: (text: string) => void;
}

const STATUS_LABEL: Record<ChatResponse['status'], string> = {
  ANSWERED: '품셈 상담',
  OUT_OF_SCOPE: '범위 밖',
  EVIDENCE_ONLY: '근거만 제공',
  MISSING_INFO: '확인이 필요합니다',
  COMPUTED: '계산 완료',
  OK: '금액 계산 완료',
  PARTIAL: '부분 금액 계산',
  BLOCKED: '계산 보류',
  ERROR: '오류',
};

const BLOCKED_HINTS: Record<string, string> = {
  reset_status: '재셋팅 여부를 "없음"으로 답하면 계산됩니다.',
};

function choiceLabel(value: ChoiceValue): string {
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  return value;
}

function won(value: string | null | undefined): string {
  if (value == null) return '—';
  const [whole, fraction] = value.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${fraction === undefined ? grouped : `${grouped}.${fraction}`}원`;
}

function percent(rate: string | undefined): string {
  if (!rate) return '—';
  const [whole, fraction = ''] = rate.split('.');
  const digits = (whole + fraction).replace(/^0+/, '') || '0';
  const point = digits.length + 2 - fraction.length;
  const shifted = point <= 0 ? `0.${'0'.repeat(-point)}${digits}`
    : point >= digits.length ? `${digits}${'0'.repeat(point - digits.length)}`
      : `${digits.slice(0, point)}.${digits.slice(point)}`;
  return `${shifted.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')}%`;
}

// choices에 담긴 절 제목("6-1-4 콘크리트 펌프차 타설...")에서 앞의 절 번호만 뽑아 답으로 보낸다.
function sectionNoFromTitle(title: string): string {
  const match = title.match(/^\d+(?:-\d+){2}/);
  return match ? match[0] : title;
}

function DecisionTable({ table }: { table: NonNullable<AgentQuestion['decision_table']> }) {
  return (
    <details className="decision-table">
      <summary>판정표 보기</summary>
      <ul>
        {Object.entries(table).map(([value, row]) => (
          <li key={value}>
            <strong>{value}</strong>
            <span>{row.적용기준 ?? ''}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function QuestionCard({
  question, selectedLabel, onSelect, disabled,
}: {
  question: AgentQuestion;
  selectedLabel: string | undefined;
  onSelect: (value: ChoiceValue, label: string) => void;
  disabled: boolean;
}) {
  const isWork = question.name === 'work';
  return (
    <div className="question-card">
      <div className="question-ask">{question.ask}</div>
      {question.reason && <div className="question-reason">{question.reason}</div>}
      {question.hint && (
        <div className="question-hint">
          힌트: {question.hint.matched} → {question.hint.value}일 수 있습니다 (자동 선택 아님, 확인 필요)
        </div>
      )}
      {question.choices && (
        <div className="question-choices">
          {question.choices.map((choice) => {
            const label = typeof choice === 'string' ? (question.labels?.[choice] ?? choiceLabel(choice)) : choiceLabel(choice);
            const value: ChoiceValue = isWork && typeof choice === 'string' ? sectionNoFromTitle(choice) : choice;
            const isDefault = isWork && question.default === value;
            const isSelected = selectedLabel === label;
            return (
              <button
                key={label}
                type="button"
                className={`choice-btn${isSelected ? ' selected' : ''}${isDefault && !selectedLabel ? ' is-default' : ''}`}
                disabled={disabled}
                onClick={() => onSelect(value, label)}
              >
                {label}
                {isDefault && <span className="choice-default-tag">기본값</span>}
              </button>
            );
          })}
        </div>
      )}
      {question.decision_table && <DecisionTable table={question.decision_table} />}
      {question.citations && question.citations.length > 0 && <CitationList citations={question.citations} />}
    </div>
  );
}

function EvidenceList({ items }: { items: ChatResponse['evidence'] }) {
  if (items.length === 0) return null;
  return (
    <details className="evidence-disclosure">
      <summary>📖 근거 {items.length}개</summary>
      <div className="evidence-list">
        {items.map((item, i) => (
          <div className="evidence-row" key={i}>
            <div className="evidence-head">
              <strong>{item.section}</strong>
              <span>PDF {item.page}쪽{item.table_id ? ` · ${item.table_id}` : ''}</span>
            </div>
            <p>{item.snippet}</p>
          </div>
        ))}
      </div>
    </details>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  const setOpenImage = useContext(SourcePanelContext);
  const first = citations[0];
  const citationSummary = citations.length === 1 && first
    ? `근거 · ${first.section} (p.${first.pdf_page ?? '—'})`
    : `근거 ${citations.length}개`;
  return (
    <details className="citation-disclosure">
      <summary>{citationSummary}</summary>
      <div className="citation-list">
        {citations.map((citation, index) => (
          <div className="citation-item" key={`${citation.internal_id}-${index}`}>
            <div className="citation-label">
              {citation.quote ? citation.label.split('\n').slice(0, 2).join('\n') : citation.label}
            </div>
            {citation.quote && <blockquote className="md-bq"><strong>{citation.item}</strong> “{citation.quote}”</blockquote>}
            {citation.reason && <div>{citation.reason}</div>}
            {citation.pdf_page != null && (citation.image_url ?
              <button type="button" className="source-page-badge" onClick={() => setOpenImage(citation)} aria-label={`PDF ${citation.pdf_page}쪽 원문 보기`}>p.{citation.pdf_page}</button> :
              <span className="source-page-badge">p.{citation.pdf_page}</span>)}
            {citation.image_url && <button type="button" className="source-image-button"
              onClick={() => setOpenImage(citation)}>원문 보기</button>}
            <details className="citation-internal"><summary>자세히</summary>
              <small>내부 ID: {citation.internal_id} · PDF {citation.pdf_page}쪽</small>
            </details>
          </div>
        ))}
      </div>
    </details>
  );
}

const SourcePanelContext = createContext<(citation: Citation | null) => void>(() => undefined);

function SourceViewer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const apiBase = process.env.REACT_APP_API_URL ?? '';
  const imageUrl = citation.image_url?.startsWith('/') ? `${apiBase}${citation.image_url}` : citation.image_url;
  return (
    <div className="source-viewer-backdrop" role="presentation" onClick={onClose}>
      <section className="source-viewer" role="dialog" aria-modal="true" aria-label="표 원문"
        onClick={(event) => event.stopPropagation()}>
        <header className="source-viewer-header">
          <strong>표 원문 · PDF {citation.pdf_page ?? '—'}쪽</strong>
          <button type="button" onClick={onClose} aria-label="원문 패널 닫기">×</button>
        </header>
        <div className="source-viewer-image">
          <img src={imageUrl ?? ''} alt={`${citation.section_no} ${citation.subsection ?? ''} 표 원문`} />
        </div>
      </section>
    </div>
  );
}

function MarkdownAnswer({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    h2: ({ children: content }) => <h2 className="md-h2">{content}</h2>,
    h3: ({ children: content }) => <h3 className="md-h3">{content}</h3>,
    p: ({ children: content }) => <p className="md-p">{content}</p>,
    li: ({ children: content }) => <li className="md-li">{content}</li>,
    blockquote: ({ children: content }) => <blockquote className="md-bq">{content}</blockquote>,
    table: ({ children: content }) => <div className="md-table-wrap"><table className="md-table">{content}</table></div>,
    code: ({ children: content, className }) => className
      ? <code className={className}>{content}</code>
      : <code className="md-code-inline">{content}</code>,
    pre: ({ children: content }) => <pre className="md-pre">{content}</pre>,
  }}>{children}</ReactMarkdown>;
}

function AssistantTiming({ response, elapsedMs }: { response: ChatResponse; elapsedMs?: number }) {
  const [showTiming, setShowTiming] = useState(false);
  const timing = response.timing;
  const total = timing?.total_ms ?? 0;
  const detail = timing ? Math.max(0, total - timing.route_ms - timing.retrieve_ms - timing.compute_ms - timing.llm_ms) : 0;
  if (elapsedMs == null) return null;
  return (
    <div className="assistant-timing">
      <span className="think-label">{`${(elapsedMs / 1000).toFixed(1)}\uCD08 \uB3D9\uC548 \uC0DD\uAC01\uD568`}</span>
      {timing && <button type="button" className="timing-toggle" onClick={() => setShowTiming((open) => !open)}>
        {showTiming ? '\uC811\uAE30' : '\uC790\uC138\uD788'}
      </button>}
      {showTiming && timing && <div className="timing-details">{`\uC9C8\uBB38 \uBD84\uB958 ${(timing.route_ms / 1000).toFixed(1)}\uCD08 ? \uAC80\uC0C9 ${(timing.retrieve_ms / 1000).toFixed(1)}\uCD08 ? \uACC4\uC0B0 ${(timing.compute_ms / 1000).toFixed(1)}\uCD08 ? \uB2F5\uBCC0 \uC791\uC131 ${(timing.llm_ms / 1000).toFixed(1)}\uCD08 ? \uAE30\uD0C0 ${(detail / 1000).toFixed(1)}\uCD08`}</div>}
    </div>
  );
}

function AssistantActionBar({ response, receivedAtMs }: { response: ChatResponse; receivedAtMs?: number }) {
  const [copied, setCopied] = useState(false);
  const time = receivedAtMs ? new Date(receivedAtMs).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '';
  const copy = () => {
    void navigator.clipboard?.writeText(response.answer ?? response.message);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="action-bar">
      <button type="button" className="action-btn" onClick={copy} title="복사" aria-label="복사">
        {copied ? <Check size={16} strokeWidth={1.75} aria-hidden="true" /> : <Copy size={16} strokeWidth={1.75} aria-hidden="true" />}
      </button>
      {['OK', 'PARTIAL'].includes(response.status) &&
        <button className="action-btn export-link" onClick={() => downloadEstimate(response.thread_id).catch(() => showToast('견적서 다운로드에 실패했습니다. 다시 시도해 주세요.', 'error'))} title="Excel 다운로드">
          <Download size={16} strokeWidth={1.75} aria-hidden="true" /><span>Excel</span>
        </button>}
      {time && <time className="msg-time">{time}</time>}
    </div>
  );
}
function EstimateTabs({ tabs, resetToken }: {
  tabs: { id: string; label: string; content: React.ReactNode }[]; resetToken: object;
}) {
  const prefix = useId();
  const [selected, setSelected] = useState(tabs[0]?.id);
  useEffect(() => { setSelected(tabs[0]?.id); }, [resetToken]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = tabs.find(tab => tab.id === selected) ?? tabs[0];
  if (!active) return null;
  return <div className="estimate-tabs">
    <div className="estimate-tab-row" role="tablist" aria-label="견적 결과">
      {tabs.map((tab, index) => <button type="button" key={tab.id}
        id={`${prefix}-${tab.id}`} role="tab" aria-selected={active.id === tab.id}
        aria-controls={`${prefix}-panel`} tabIndex={active.id === tab.id ? 0 : -1}
        onClick={() => setSelected(tab.id)} onKeyDown={event => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
          setSelected(next.id);
          document.getElementById(`${prefix}-${next.id}`)?.focus();
        }}>{tab.label}</button>)}
    </div>
    <div id={`${prefix}-panel`} role="tabpanel" aria-labelledby={`${prefix}-${active.id}`} tabIndex={0}>
      {active.content}
    </div>
  </div>;
}

function ComputedCard({ work, inputs, result, priced, tables, response }: {
  response: ChatResponse;
  work: ChatResponse['work']; inputs: ChatResponse['inputs']; result: ComputedResult; priced: PricedResult | null;
  tables: ChatResponse['tables'];
}) {
  const priceByName = new Map(priced?.lines.map((line) => [line.name, line]) ?? []);
  const conditionNames = ['structure', 'slump_band', 'facility_type', 'site_type', 'placement', 'vibrator_used', 'pump_size'];
  const conditions = inputs.filter((item) => conditionNames.includes(item.name))
    .map((item) => `${item.label} ${choiceLabel(item.value)}`).join(' · ');
  return (
    <div className="computed-card">
      <EstimateTabs resetToken={response} tabs={[
        ...(tables.statement_rows.length ? [{ id: 'statement', label: '원가계산서', content:
          <StatementTable rows={tables.statement_rows} notes={response.statement?.basis_notes ?? []} /> }] : []),
        ...(tables.bill ? [{ id: 'bill', label: '내역서', content: <BillTable bill={tables.bill} /> }] : []),
        ...(result.unit_lines.length ? [{ id: 'unit', label: `일위대가표 (${result.unit_basis.per}당)`, content: <div>
      <div className="unit-summary">{work?.title}{conditions && ` · ${conditions}`}</div>
      <div className="unit-note">{priced?.rate_version
        ? `노임단가: ${priced.rate_version.id.slice(0, 4)} ${priced.rate_version.id.endsWith('H2') ? '하반기' : '상반기'} (${priced.rate_version.effective_from} 적용)`
        : '적용 가능한 노임단가 없음'}</div>
      <div className="unit-note">{priced?.equipment_rate_version
        ? `건설기계 경비: ${priced.equipment_rate_version.version}년도 (${priced.equipment_rate_version.published} 공표, ${priced.equipment_rate_version.effective_from}~${priced.equipment_rate_version.effective_to} 적용)`
        : '기준일에 적용 가능한 건설기계 경비산출표 없음'}</div>
      {result.adjustment_memos?.map((memo, index) => <div className="unit-note" key={index}>{memo}</div>)}
      <div className="table-scroll"><table className="inputs-table unit-table">
        <thead>
          <tr><th>구분</th><th>명칭</th><th>단위</th><th>수량</th><th>단가</th><th>{result.unit_basis.per}당 금액</th></tr>
        </thead>
        <tbody>
          {result.unit_lines.map((line) => {
            const price = priceByName.get(line.name);
            if (line.kind === 'equipment' && priced?.equipment_lines?.length) {
              return <React.Fragment key={line.name}>{priced.equipment_lines.map((part) =>
                <tr key={part.name}>
                  <td>{part.category}</td>
                  <td>기계경비 · {part.name}{part.machine_spec && <small> ({part.machine_spec})</small>}</td>
                  <td>{line.unit}</td>
                  <td><details className="unit-quantity"><summary>{line.applied}</summary>
                    <div>산식: {line.formula}</div><div>정확한 값: {line.exact}</div>
                    <CitationList citations={line.citations} /></details></td>
                  <td>{part.unit_price ? <details className="price-detail"><summary>{won(part.unit_price)}/hr</summary>
                    <CitationList citations={part.citations} /></details> : '—'}</td>
                  <td>{part.amount ? <details className="price-detail"><summary>{won(part.amount)}</summary>
                    <div>버림 전: {won(part.amount_exact)}</div>
                    <CitationList citations={part.citations} /></details> :
                    <span>— {part.reason}{part.fuel_l_per_unit && ` · 필요 연료 ${part.fuel_l_per_unit}ℓ/㎥`}</span>}</td>
                </tr>)}</React.Fragment>;
            }
            return (
            <tr key={line.name}>
              <td>{line.kind === 'labor' ? '노무' : line.kind === 'material' ? '재료' : '장비'}</td>
              <td>{line.name}</td>
              <td>{line.unit}</td>
              <td><details className="unit-quantity" title={`${line.formula} = ${line.exact}; ${line.rule}`}>
                <summary>{line.applied}</summary>
                <div>산식: {line.formula}</div>
                <div>정확한 값: {line.exact}</div>
                <div>자릿수: {line.rule}</div>
                {line.adjustments?.map((item, index) => <div key={index}>{item.종류} {item.값}: {item['원문 인용']}</div>)}
                <CitationList citations={line.citations} />
              </details></td>
              <td>{price?.unit_price ? <details className="price-detail"><summary>{won(price.unit_price)}</summary>
                <CitationList citations={price.citations} /></details> : '—'}</td>
              <td>{price?.amount ? <details className="price-detail"><summary>{won(price.amount)}</summary>
                <div>버림 전: {won(price.amount_exact)}</div>
                <CitationList citations={price.citations} /></details> : `— ${price?.reason ?? ''}`}</td>
            </tr>
          ); })}
          {priced?.supply_lines?.map((line) => (
            <tr key={line.name} className={line.status === '제외' ? 'excluded-row' : undefined}>
              <td>{line.category}</td>
              <td>{line.name}
                <span className={`supply-status-badge${line.status === '제외' ? ' excluded' : ''}`}>
                  {line.status}
                </span>
                {line.allowance && <small>할증 {percent(line.allowance)}</small>}
              </td>
              <td>{line.status === '산정' ? line.unit : '—'}</td>
              <td>{line.status === '산정' ? line.quantity : '—'}</td>
              <td>{line.unit_price ? <details className="price-detail"><summary>{won(line.unit_price)}</summary>
                <CitationList citations={line.citations} /></details> : '—'}</td>
              <td>{line.amount ? <details className="price-detail"><summary>{won(line.amount)}</summary>
                <div>버림 전: {won(line.amount_exact)}</div><CitationList citations={line.citations} />
              </details> : <span>— {line.reason}</span>}</td>
            </tr>
          ))}
          {priced?.cost_lines.map((line) => <tr key={line.name}>
            <td>{line.category}</td><td>{line.name}</td><td>노무비</td>
            <td>{percent(line.rate)}</td><td>{won(priced.labor_subtotal)}</td>
            <td>{line.amount ? <details className="price-detail"><summary>{won(line.amount)}</summary>
              <div>버림 전: {won(line.amount_exact)}</div><CitationList citations={line.citations} />
            </details> : '—'}</td>
          </tr>)}
        </tbody>
      </table></div>
      <div className="unit-note">{result.unit_basis.adjustable_note}</div>
      {priced && <div className="table-scroll"><table className="inputs-table price-summary-table"><tbody>
        <tr><th>{result.unit_basis.per}당 재료비 소계</th><td>{won(priced.subtotals['재료비'])}</td></tr>
        <tr><th>{result.unit_basis.per}당 노무비 소계</th><td>{won(priced.subtotals['노무비'])}</td></tr>
        <tr><th>{result.unit_basis.per}당 경비 소계</th><td>{won(priced.subtotals['경비'])}</td></tr>
        <tr><th>{priced.partial ? `${result.unit_basis.per}당 부분 합계` : `${result.unit_basis.per}당 계`}</th>
          <td>{won(priced.total)}{priced.total_exact && ` (계금 버림 전 ${won(priced.total_exact)})`}</td></tr>
      </tbody></table></div>}
      {priced?.reference_amounts?.total != null && <div className="unit-note">
        <strong>{priced.reference_amounts.volume}{result.unit_basis.per.slice(1)} 기준 참고 금액({priced.partial ? '부분' : '전체'}): {won(priced.reference_amounts.total)}</strong>
        {priced.partial && <div>빠진 항목: {[...(priced.unpriced ?? []), ...(priced.excluded ?? [])]
          .map((item) => item.name).filter((name, index, names) => names.indexOf(name) === index).join(', ') || '없음'}</div>}
        <div>내역서 작성 전 참고 금액이며, 제외·미산정 항목이 반영되지 않았습니다.</div>
      </div>}
      </div> }] : []),
        ...(tables.rate_rows.length ? [{ id: 'rates', label: '단가대비표', content: <RateTable rows={tables.rate_rows} /> }] : []),
        ...(result.lines.length || result.daily_volume ? [{ id: 'basis', label: '산출근거', content: <div className="calculation-details">
        {result.daily_volume && result.work_days && <><div className="formula-row"><span className="formula-label">일당시공량</span>
          <strong>{result.daily_volume.value} {result.daily_volume.unit}</strong>
          <span className="formula-text">{result.daily_volume.formula}</span></div>
        <div className="formula-row"><span className="formula-label">작업조 투입량</span>
          <strong>{result.work_days.value} 작업조·일</strong>
          <span className="formula-text">{result.work_days.formula}</span></div>
        <p className="unit-note">작업조 투입량은 실제 공사 기간이 아닙니다.</p></>}
        <div className="table-scroll"><table className="inputs-table lines-table">
          <thead><tr><th>구분</th><th>항목</th><th>총 투입량</th><th>단위</th><th>작업조 인원</th><th>적용 규칙</th></tr></thead>
          <tbody>{result.lines.map((line) => <tr key={line.name}>
            <td>{line.kind === 'labor' ? '노무' : '장비'}</td><td>{line.name}</td><td>{line.value}</td>
            <td>{line.unit}</td><td>{line.crew ?? '—'}</td>
            <td>{line.rules.length > 0 ? '인원 조정 적용' : '—'}</td>
          </tr>)}</tbody>
        </table></div>
      </div> }] : []),
      ]} />
        <div className="source-list"><strong>일당시공량 출처</strong>
          {result.daily_volume && <CitationList citations={result.daily_volume.citations} />}
          {result.lines.map((line) => <div key={line.name}><strong>{line.name} 작업조·조정 근거</strong>
            <CitationList citations={line.citations} /></div>)}
        </div>

      <div className="not-calculated">
        <h4>미산정 항목</h4>
        <ul>
          {(priced?.unpriced ?? result.not_calculated.map((item) => ({ name: item.item, reason: '미산정' })))
            .map((item, i) => <li key={i}>{item.name}: {item.reason}</li>)}
        </ul>
      </div>
    </div>
  );
}

function BlockedCard({ result }: { result: BlockedResult }) {
  return (
    <div className="blocked-card">
      <CitationList citations={result.citations} />
      <p className="blocked-hint">{BLOCKED_HINTS[result.input] ?? `${result.input} 값을 바꾸면 계산될 수 있습니다.`}</p>
    </div>
  );
}

function WarningBanner({ warnings, raw }: { warnings: string[]; raw?: string[] }) {
  useEffect(() => {
    if (raw && raw.length > 0) console.warn('[search fallback]', raw);
  }, [raw]);
  if (warnings.length === 0) return null;
  return (
    <div className="search-note">
      {warnings.map((warning, i) => <div key={i}>{warning}</div>)}
    </div>
  );
}

function AssistantCard({
  response, interactive, draft, onSelect, onSubmit, loading, onChangeConditions,
  elapsedMs, receivedAtMs,
}: {
  response: ChatResponse;
  onChangeConditions: (conditions: Record<string, string>) => void;
  interactive: boolean;
  draft: Record<string, { value: ChoiceValue; label: string }>;
  onSelect: (name: string, value: ChoiceValue, label: string) => void;
  onSubmit: () => void;
  loading: boolean;
  elapsedMs?: number;
  receivedAtMs?: number;
}) {
  const amountRow = response.route === 'estimate'
    ? response.tables.statement_rows.find((row) => row.name === '도급액' && row.amount != null)
    : undefined;
  const bill = response.tables.bill;
  return (
    <div className={`assistant-card status-${response.status.toLowerCase()}`}>
      <WarningBanner warnings={response.search.warnings} raw={response.search.raw_warnings} />
      <div className="assistant-card-header">
        <span className={`agent-badge route-${response.route ?? 'unknown'}`}><span className="agent-badge-dot" />
          {response.route === 'estimate' ? '견적' : response.route === 'qa' ? '상담' : response.route === 'out_of_scope' ? '범위 밖' : STATUS_LABEL[response.status]}
        </span>
        {response.work && <span className="work-badge">{response.work.section_no ? `${response.work.section_no} ` : ''}{response.work.title}</span>}
        {response.answer_source === 'template' && <span className="simple-answer-badge">간단 응답</span>}
        <AssistantTiming response={response} elapsedMs={elapsedMs} />
      </div>
      {amountRow && <div className="estimate-amount-block">
        <strong>도급액 {won(String(amountRow.amount))} (부가세 포함{bill ? ` · ${bill.quantity}${bill.unit}` : ''})</strong>
        <span>표준품셈 기준 참고 금액</span>
      </div>}
      {response.status === 'ANSWERED' && response.qa ? (
        <div className="qa-card">
          <MarkdownAnswer>{`**${response.qa.conclusion}**${response.qa.explanation ? `\n\n${response.qa.explanation}` : ''}`}</MarkdownAnswer>
          {response.qa.comparisons.length > 0 && <ul>{response.qa.comparisons.map((item, i) =>
            <li className="md-li" key={i}><strong>{item.section}:</strong>
              {(response.answer_source === 'template' || response.qa!.not_found_kind === 'section_found_value_missing') && item.citation_ids ?
                <CitationList citations={response.qa!.citations.filter(c => item.citation_ids!.includes(c.chunk_id))} /> :
                <span>{item.summary}</span>}
            </li>)}</ul>}
          {response.answer_source !== 'template' && response.qa.not_found_kind !== 'section_found_value_missing' && response.qa.citations.length > 0 && <div>
            <CitationList citations={response.qa.citations} /></div>}
        </div>
      ) : response.answer ? (
        <div className="assistant-answer">
          <div className="assistant-text"><MarkdownAnswer>{response.answer}</MarkdownAnswer></div>
        </div>
      ) : (
        <div className="assistant-text"><MarkdownAnswer>{response.message}</MarkdownAnswer></div>
      )}

      {response.status === 'EVIDENCE_ONLY' && <EvidenceList items={response.evidence} />}

      {response.status === 'MISSING_INFO' && (
        <div className="question-list">
          {response.questions.map((question) => (
            <QuestionCard
              key={question.name}
              question={question}
              selectedLabel={draft[question.name]?.label}
              disabled={!interactive || loading}
              onSelect={(value, label) => onSelect(question.name, value, label)}
            />
          ))}
          {interactive && (
            <button
              type="button"
              className="submit-answers-btn"
              disabled={loading || Object.keys(draft).length === 0}
              onClick={onSubmit}
            >
              보내기
            </button>
          )}
        </div>
      )}

      {['OK', 'PARTIAL'].includes(response.status) && response.tables.statement_rows.length > 0 && (
        <>
          <ConditionsBar key={JSON.stringify(response.conditions)}
            conditions={response.conditions} disabled={!interactive || loading}
            onApply={onChangeConditions} />
          {!response.result && <EstimateTabs resetToken={response} tabs={[
            { id: 'statement', label: '원가계산서', content: <StatementTable rows={response.tables.statement_rows} notes={response.statement?.basis_notes ?? []} /> },
          ]} />}
        </>
      )}

      {['COMPUTED', 'OK', 'PARTIAL'].includes(response.status) && response.result && (
        <ComputedCard work={response.work} inputs={response.inputs} result={response.result as ComputedResult}
          priced={response.priced} tables={response.tables} response={response} />
      )}

      {response.status === 'BLOCKED' && response.result && (
        <BlockedCard result={response.result as BlockedResult} />
      )}
      <AssistantActionBar response={response} receivedAtMs={receivedAtMs} />
    </div>
  );
}

function ChatAreaView({ turns, loading, onSendMessage, onSendAnswers, onChangeConditions, onSendExample }: Props) {
  const [input, setInput] = useState('');
  const [draft, setDraft] = useState<Record<string, { value: ChoiceValue; label: string }>>({});
  const [showExampleMenu, setShowExampleMenu] = useState(false);
  const [thinkNow, setThinkNow] = useState(Date.now());
  const [loadingSince, setLoadingSince] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const exampleMenuRef = useRef<HTMLDivElement>(null);

  const lastTurn = turns[turns.length - 1];
  const lastResponse = lastTurn?.role === 'assistant' ? lastTurn.response : undefined;
  const activeUserTurn = turns[turns.length - 1]?.role === 'user' ? turns[turns.length - 1] : undefined;
  const thinkingSeconds = Math.max(0, (thinkNow - (activeUserTurn?.sentAtMs ?? loadingSince ?? thinkNow)) / 1000);

  useEffect(() => {
    if (!loading) return;
    setLoadingSince(Date.now());
    const timer = window.setInterval(() => setThinkNow(Date.now()), 1000);
    return () => { window.clearInterval(timer); setLoadingSince(null); };
  }, [loading]);

  useEffect(() => {
    if (lastResponse?.status === 'MISSING_INFO') {
      const initial: Record<string, { value: ChoiceValue; label: string }> = {};
      const workQuestion = lastResponse.questions.find((q) => q.name === 'work');
      if (workQuestion?.default && workQuestion.choices) {
        const defaultChoice = workQuestion.choices.find(
          (choice) => typeof choice === 'string' && sectionNoFromTitle(choice) === workQuestion.default,
        );
        if (typeof defaultChoice === 'string') {
          initial.work = { value: workQuestion.default, label: choiceLabel(defaultChoice) };
        }
      }
      setDraft(initial);
    } else {
      setDraft({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastTurn?.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, loading]);

  useEffect(() => {
    if (!showExampleMenu) return;
    const handleOutsideClick = (e: MouseEvent) => {
      if (exampleMenuRef.current && !exampleMenuRef.current.contains(e.target as Node)) {
        setShowExampleMenu(false);
      }
    };
    const handleEscape = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowExampleMenu(false); };
    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleEscape);
    return () => { document.removeEventListener('mousedown', handleOutsideClick); document.removeEventListener('keydown', handleEscape); };
  }, [showExampleMenu]);

  const handleExampleClick = useCallback((text: string) => {
    setShowExampleMenu(false);
    onSendExample(text);
  }, [onSendExample]);

  const handleSelect = useCallback((name: string, value: ChoiceValue, label: string) => {
    setDraft((prev) => ({ ...prev, [name]: { value, label } }));
  }, []);

  const handleSubmitAnswers = useCallback(() => {
    const answers: Record<string, ChoiceValue> = {};
    const parts: string[] = [];
    for (const [name, entry] of Object.entries(draft)) {
      answers[name] = entry.value;
      parts.push(entry.label);
    }
    onSendAnswers(answers, parts.join(', ') || '답변을 보냈습니다');
  }, [draft, onSendAnswers]);

  const handleSubmitMessage = () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onSendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSubmitMessage(); }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 160) + 'px'; }
  };

  const renderInputBox = (withExampleMenu: boolean) => (
    <div className="input-box">
      {withExampleMenu && (
        <div className="example-menu-wrap" ref={exampleMenuRef}>
          <button
            type="button"
            className="example-menu-btn"
            aria-label="예시 질문 보기"
            aria-expanded={showExampleMenu}
            disabled={loading}
            onClick={() => setShowExampleMenu((prev) => !prev)}
          >
            <ChatIcon name="plus" />
          </button>
          {showExampleMenu && (
            <div className="example-menu">
              {EXAMPLE_QUESTIONS.map((ex) => (
                <button
                  key={ex.text}
                  type="button"
                  className="example-menu-item"
                  onClick={() => handleExampleClick(ex.text)}
                  title={ex.text}
                >
                  <span className={`example-kind ${ex.kind === '견적' ? 'estimate' : 'qa'}`}>{ex.kind}</span>
                  <span>{ex.text}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder="무엇이든 물어보세요"
        aria-label="질문 입력"
        rows={1}
        disabled={loading}
      />
      <button className="send-btn" aria-label="질문 보내기" onClick={handleSubmitMessage} disabled={!input.trim() || loading}>
        <ChatIcon name="arrow" />
      </button>
    </div>
  );

  if (turns.length === 0) {
    return (
      <main className="chat-area">
        <div className="centered-welcome">
          <div className="welcome-header">
            <h2>무엇을 도와드릴까요?</h2>
          </div>
          <div className="centered-input-area">{renderInputBox(true)}</div>
          <div className="example-prompts">
            {EXAMPLE_QUESTIONS.map((ex, index) => (
              <button key={ex.text} className="example-btn" disabled={loading} onClick={() => onSendExample(ex.text)} title={ex.text}>
                <span>{['자동문 설치 견적', '콘크리트 타설 견적', '진동기 적용 기준', '기초앵커 품셈 상담'][index] ?? ex.text}</span>
              </button>
            ))}
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="chat-area">
      <div className="messages-wrap">
        <div className="messages">
          {turns.map((turn, i) => (
            <div key={turn.id} className={`message ${turn.role}`}>
              {turn.role === 'user' ? (
                <div className="user-msg-wrap">
                  <div className="user-bubble">{turn.text}</div>
                </div>
              ) : (
                <div className="assistant-body">
                  {turn.response && (
                    <AssistantCard
                      response={turn.response}
                      elapsedMs={turn.elapsedMs}
                      receivedAtMs={turn.receivedAtMs}
                      interactive={i === turns.length - 1}
                      draft={draft}
                      onSelect={handleSelect}
                      onSubmit={handleSubmitAnswers}
                      loading={loading}
                      onChangeConditions={(conditions) => onChangeConditions(turn.id, conditions)}
                    />
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="message assistant">
              <div className="loading-indicator">
                <svg width="26" height="20" viewBox="0 0 40 30" fill="none">
                  <rect className="brick b1" x="0" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b2" x="13" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b3" x="26" y="22" width="11" height="7" rx="1.5" fill="#3a7d44" />
                  <rect className="brick b4" x="6" y="14" width="11" height="7" rx="1.5" fill="#2e6436" />
                  <rect className="brick b5" x="20" y="14" width="11" height="7" rx="1.5" fill="#2e6436" />
                  <rect className="brick b6" x="13" y="6" width="11" height="7" rx="1.5" fill="#14532d" />
                </svg>
                <span className="think-label animate">{thinkingSeconds.toFixed(0)}초 동안 생각 중...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="input-area">{renderInputBox(true)}<p className="composer-note">견적은 참고용 초안입니다. 사용 전 산출근거를 확인해 주세요.</p></div>
    </main>
  );
}

function ChatIcon({ name }: { name: 'plus' | 'panel' | 'settings' | 'feedback' | 'arrow' }) {
  const icons = { plus: Plus, panel: PanelLeft, settings: Settings, feedback: MessageSquareText, arrow: ArrowUp };
  const Icon = icons[name];
  return <Icon size={name === 'panel' ? 22 : 20} strokeWidth={1.75} aria-hidden="true" />;
}

export default function ChatArea(props: Props) {
  const [openSource, setOpenSource] = useState<Citation | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 900);
  const [conversationKey, setConversationKey] = useState(0);
  const newChat = () => { setOpenSource(null); setConversationKey(key => key + 1); props.onNewChat(); if (window.innerWidth < 900) setSidebarOpen(false); };

  useEffect(() => {
    if (!window.matchMedia) return;
    const desktop = window.matchMedia('(min-width: 900px)');
    const updateLayout = (event: MediaQueryListEvent) => setSidebarOpen(event.matches);
    desktop.addEventListener('change', updateLayout);
    return () => desktop.removeEventListener('change', updateLayout);
  }, []);

  useEffect(() => {
    if (!sidebarOpen) return;
    const closeMenu = (event: KeyboardEvent) => { if (event.key === 'Escape' && window.innerWidth < 900) setSidebarOpen(false); };
    window.addEventListener('keydown', closeMenu);
    return () => window.removeEventListener('keydown', closeMenu);
  }, [sidebarOpen]);

  useEffect(() => {
    if (!openSource) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenSource(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [openSource]);

  return (
    <SourcePanelContext.Provider value={setOpenSource}>
      <div className={`chat-shell${openSource ? ' with-source' : ''}`}>
        {sidebarOpen && <>
          <button className="chat-sidebar-backdrop" aria-label="메뉴 닫기" onClick={() => setSidebarOpen(false)} />
          <aside id="chat-sidebar" className="chat-sidebar" aria-label="채팅 메뉴">
            <div className="chat-sidebar-brand"><a href="/" aria-label="품셈이 홈">품셈이</a><button className="chat-icon-button" aria-label="사이드바 닫기" onClick={() => setSidebarOpen(false)}><ChatIcon name="panel" /></button></div>
            <nav className="chat-nav">
              <button className={!props.activeConversationId ? 'chat-nav-active' : undefined} aria-current={!props.activeConversationId ? 'page' : undefined} disabled={props.loading} onClick={newChat}><ChatIcon name="plus" />새 대화</button>
            </nav>
            {!!props.conversations?.length && <nav className="chat-history" aria-label="이전 대화"><h2>대화</h2>{props.conversations.map(chat => <button key={chat.id} title={chat.title} aria-current={chat.id === props.activeConversationId ? 'page' : undefined} className={chat.id === props.activeConversationId ? 'chat-history-active' : undefined} disabled={props.loading} onClick={() => { setOpenSource(null); props.onSelectConversation?.(chat.id); if (window.innerWidth < 900) setSidebarOpen(false); }}><span>{chat.title}</span></button>)}</nav>}
            <div className="chat-sidebar-bottom">
              <button className="chat-sidebar-action" onClick={props.onSettings}><ChatIcon name="settings" />설정</button>
              <button className="chat-sidebar-action" onClick={() => showToast('피드백 기능은 준비 중입니다.')}><ChatIcon name="feedback" />피드백 남기기</button>
              {props.accountLabel ? <button className="chat-account" onClick={props.onSettings} aria-label="계정 설정"><span className="chat-account-avatar" aria-hidden="true">{props.accountLabel.slice(0, 1).toUpperCase()}</span><span className="chat-account-name">{props.accountLabel}</span><ChevronDown size={16} strokeWidth={1.75} /></button> : <div className="chat-sidebar-login"><strong>품셈이와 함께 시작하세요</strong><p>공사비 견적부터 품셈 상담까지,<br />한곳에서 쉽고 간편하게.</p><button disabled={props.authLoading || props.loading} onClick={props.onLogin}>{props.authLoading ? '로그인 확인 중…' : '로그인'}</button></div>}
            </div>
          </aside>
        </>}
        <div className="chat-workspace">
          <header className="chat-header"><div>{!sidebarOpen && <button className="chat-icon-button" aria-label="사이드바 열기" aria-expanded={sidebarOpen} aria-controls="chat-sidebar" onClick={() => setSidebarOpen(true)}><ChatIcon name="panel" /></button>}<span>품셈이</span><span className="chat-header-caption">표준품셈 AI</span></div><button className="chat-icon-button" aria-label="새 대화 시작" title="새 대화" disabled={props.loading} onClick={newChat}><ChatIcon name="plus" /></button></header>
          <ChatAreaView key={`${props.activeConversationId ?? 'new'}:${conversationKey}`} {...props} />
        </div>
        {openSource?.image_url && <SourceViewer citation={openSource} onClose={() => setOpenSource(null)} />}
      </div>
    </SourcePanelContext.Provider>
  );
}

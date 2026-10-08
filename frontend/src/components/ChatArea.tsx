import React, { useId, createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUp, Check, Copy, Download, Info, MessageSquareText, PanelLeft, Plus, Settings } from 'lucide-react';
import { AgentQuestion, BlockedResult, ChatResponse, ChatTurn, ChoiceValue, Citation, ComputedResult, PricedResult, UsageStatus } from '../types';
import { downloadEstimate } from '../api';
import { EXAMPLE_QUESTIONS } from '../examples';
import { showToast } from '../toast';
import { BillTable, ConditionsBar, RateTable, StatementTable } from './StatementView';
import './ChatArea.css';
import './ChatWorkspace.css';
import ChatHistoryItem from './ChatHistoryItem';
import AccountMenu from './AccountMenu';
import AnswerFeedback from './AnswerFeedback';
import EstimateGuidance from './EstimateGuidance';
import UserQuestion from './UserQuestion';

// 지난 카드에는 선택 상태를 주지 않는다. 같은 이름의 질문(scope 등)이 다시 나와도 지금 ref의 카드만 선택된다.
const NO_DRAFT: Record<string, { value: ChoiceValue; label: string }> = {};

interface Props {
  restoring?: boolean;
  ratingUserId?: string;
  onRatingSaved?: (answerId: string, value: NonNullable<ChatResponse['answer_rating']>) => void;
  usage?: UsageStatus | null;
  inputDisabled?: boolean;
  accountLabel?: string | null;
  authLoading?: boolean;
  onLogin?: () => void;
  onSettings?: () => void;
  onFeedback?: () => void;
  onLogout?: () => void;
  logoutBusy?: boolean;
  logoutError?: string;
  conversations?: { id: string; title: string }[];
  activeConversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  onRenameConversation?: (id: string) => void;
  turns: ChatTurn[];
  loading: boolean;
  generating?: boolean;
  onSendMessage: (text: string) => void;
  onResendMessage?: (text: string) => void;
  onSendAnswers: (answers: Record<string, ChoiceValue>, summary: string, refs?: Record<string, string>) => void;
  onChangeConditions: (turnId: string, conditions: Record<string, string>) => void;
  onNewChat: () => void;
  onSendExample: (text: string) => void;
  expired?: boolean;
  onRecover?: () => void;
  onRetry?: (turn: ChatTurn) => void;
}

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
      {Array.isArray(question.choices) && (
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
          <strong>품셈 원문 · PDF {citation.pdf_page ?? '—'}쪽</strong>
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
  const duration = elapsedMs ?? response.timing?.total_ms;
  if (duration == null) return null;
  return <div className="assistant-timing"><span className="think-label">{(duration / 1000).toFixed(1)}초 동안 생각함</span></div>;
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
      {['OK', 'PARTIAL'].includes(response.status) &&
        <button type="button" className="action-btn export-link" onClick={() => downloadEstimate(response.thread_id).catch(error => showToast(error?.message === 'GUEST_EXPIRED'
          ? '임시 대화가 만료되어 이 견적서를 내려받을 수 없습니다.' : '견적서 다운로드에 실패했습니다. 다시 시도해 주세요.', 'error'))}>
          <Download size={19} strokeWidth={1.75} aria-hidden="true" /><span>엑셀 견적서 다운로드</span>
        </button>}
      <button type="button" className="action-btn" onClick={copy} title="복사" aria-label="복사">
        {copied ? <Check size={16} strokeWidth={1.75} aria-hidden="true" /> : <Copy size={16} strokeWidth={1.75} aria-hidden="true" />}
      </button>
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
      {result.assumptions && <p className="unit-note">{result.assumptions}</p>}
      {result.per_unit_only && <p className="unit-note">단위당 품 — 총 인원·작업일수가 필요하면 물량을 알려 주세요.</p>}
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
        {priced.partial && <div>제외·미산정 항목: {[...(priced.unpriced ?? []), ...(priced.excluded ?? [])]
          .map((item) => item.name).filter((name, index, names) => names.indexOf(name) === index).join(', ') || '없음'}</div>}
        <div>내역서 작성 전 참고 금액이며, 제외·미산정 항목이 반영되지 않았습니다.</div>
      </div>}
      </div> }] : []),
        ...(tables.rate_rows.length ? [{ id: 'rates', label: '단가대비표', content: <RateTable rows={tables.rate_rows} /> }] : []),
        ...(result.lines.length || result.daily_volume ? [{ id: 'basis', label: '산출근거', content: <div className="calculation-details">
        {work && <p className="unit-note">적용 품셈: {work.title}</p>}
        {result.daily_volume && <div className="formula-row"><span className="formula-label">일당시공량</span>
          <strong>{result.daily_volume.value} {result.daily_volume.unit}</strong>
          <span className="formula-text">{result.daily_volume.formula}</span></div>}
        {result.work_days && <><div className="formula-row"><span className="formula-label">작업조 투입량</span>
          <strong>{result.work_days.display ?? result.work_days.value} 작업조·일</strong>
          <span className="formula-text">{result.work_days.formula}</span></div>
        <p className="unit-note">작업조 투입량은 실제 공사 기간이 아닙니다.</p></>}
        {result.lines.length > 0 && <div className="table-scroll"><table className="inputs-table lines-table">
          <thead><tr><th>구분</th><th>항목</th><th>총 투입량</th><th>단위</th><th>작업조 인원</th><th>적용 규칙</th></tr></thead>
          <tbody>{result.lines.map((line) => <tr key={line.name}>
            <td>{line.kind === 'labor' ? '노무' : '장비'}</td><td>{line.name}</td><td>{line.value}</td>
            <td>{line.unit}</td><td>{line.crew ?? '—'}</td>
            <td>{line.rules.length > 0 ? '인원 조정 적용' : '—'}</td>
          </tr>)}</tbody>
        </table></div>}
      </div> }] : []),
      ]} />
        <details className="source-list"><summary>품셈 근거와 원문 확인</summary>
          {work && <p className="unit-note">적용 품셈: {work.title}</p>}
          <strong>일당시공량 출처</strong>
          {result.daily_volume && <CitationList citations={result.daily_volume.citations} />}
          {result.lines.map((line) => <div key={line.name}><strong>{line.name} 작업조·조정 근거</strong>
            <CitationList citations={line.citations} /></div>)}
        </details>

      <div className="not-calculated">
        <h4>아직 금액에 반영하지 못한 항목</h4>
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
  elapsedMs, receivedAtMs, ordinal, ratingUserId, onRatingSaved,
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
  ordinal: number;
  ratingUserId?: string;
  onRatingSaved?: Props['onRatingSaved'];
}) {
  return (
    <div className={`assistant-card status-${response.status.toLowerCase()}`}>
      <WarningBanner warnings={response.search.warnings} raw={response.search.raw_warnings} />
      <div className="assistant-card-header">
        <AssistantTiming response={response} elapsedMs={elapsedMs} />
      </div>
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

      <EstimateGuidance response={response} />

      {response.status === 'MISSING_INFO' && (
        <div className="question-list">
          {(response.questions_remaining ?? 0) >= 2 && (
            <p className="questions-remaining">남은 확인 {response.questions_remaining}개</p>
          )}
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
            <>
              {response.questions.every(question => question.ref) && draft.scope?.value !== '새 견적 시작' && (
                <p>선택한 답은 이용 횟수에서 차감되지 않아요.</p>
              )}
              <button
                type="button"
                className="submit-answers-btn"
                disabled={loading || Object.keys(draft).length === 0}
                onClick={onSubmit}
              >
                이 조건으로 견적 계산하기
              </button>
            </>
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
      {['OK', 'PARTIAL', 'COMPUTED'].includes(response.status) && <aside className="estimate-review-notice" aria-label="견적 이용 시 주의사항">
        <div className="estimate-review-heading"><Info size={17} strokeWidth={1.75} aria-hidden="true" /><strong>참고용 초안이에요. 사용 전 검토가 필요해요.</strong></div>
        <p>AI 계산에는 오류나 누락이 있을 수 있어요. 입찰·계약·발주 등에 사용하기 전에 품셈 원문, 물량·단가, 현장 조건과 미산정 항목을 담당자 또는 전문가와 확인해 주세요.</p>
        <p className="estimate-review-liability">검토 없이 사용해 발생한 경제적 손실에 대해서는 관련 법령이 허용하는 범위에서 책임을 지지 않습니다. <a href="/terms" target="_blank" rel="noopener noreferrer">이용약관 확인</a></p>
      </aside>}
      <AssistantActionBar response={response} receivedAtMs={receivedAtMs} />
      <AnswerFeedback key={response.answer_id} response={response} ordinal={ordinal} userId={ratingUserId} disabled={loading} onSaved={onRatingSaved} />
    </div>
  );
}

function ChatAreaView({ turns, loading, restoring, generating = loading, inputDisabled, onSendMessage, onResendMessage, onSendAnswers, onChangeConditions, onSendExample, ratingUserId, onRatingSaved, expired, onRecover, onRetry }: Props) {
  const blocked = loading || !!inputDisabled;
  const [input, setInput] = useState('');
  const [draft, setDraft] = useState<Record<string, { value: ChoiceValue; label: string }>>({});
  const [thinkNow, setThinkNow] = useState(Date.now());
  const [loadingSince, setLoadingSince] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lastTurn = turns[turns.length - 1];
  const lastResponse = lastTurn?.role === 'assistant' ? lastTurn.response : undefined;
  const activeUserTurn = turns[turns.length - 1]?.role === 'user' ? turns[turns.length - 1] : undefined;
  const thinkingSeconds = Math.max(0, (thinkNow - (activeUserTurn?.sentAtMs ?? loadingSince ?? thinkNow)) / 1000);

  useEffect(() => {
    if (!generating) return;
    setLoadingSince(Date.now());
    const timer = window.setInterval(() => setThinkNow(Date.now()), 1000);
    return () => { window.clearInterval(timer); setLoadingSince(null); };
  }, [generating]);

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
  }, [turns.length, generating]);

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
    const refs: Record<string, string> = {};
    for (const question of lastResponse?.questions ?? []) {
      if (question.ref && question.name in answers) refs[question.name] = question.ref;
    }
    onSendAnswers(answers, parts.join(', ') || '답변을 보냈습니다', Object.keys(refs).length ? refs : undefined);
  }, [draft, onSendAnswers, lastResponse]);

  const handleSubmitMessage = () => {
    const text = input.trim();
    if (!text || blocked) return;
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

  const renderInputBox = () => (
    <div className="input-box">
      <textarea
        maxLength={10000}
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder="무엇이든 물어보세요"
        aria-label="질문 입력"
        rows={1}
        disabled={blocked}
      />
      <button className="send-btn" aria-label="질문 보내기" onClick={handleSubmitMessage} disabled={!input.trim() || blocked}>
        <ChatIcon name="arrow" />
      </button>
    </div>
  );

  if (restoring) return <main className="chat-area" aria-busy="true"><div className="chat-restore-status" role="status">
    <span className="chat-restore-spinner" aria-hidden="true" /><span>대화를 불러오고 있어요</span>
  </div></main>;

  if (turns.length === 0) {
    return (
      <main className="chat-area">
        <div className="centered-welcome">
          <div className="welcome-header">
            <h2>무엇을 도와드릴까요?</h2>
          </div>
          <div className="centered-input-area">{renderInputBox()}</div>
          <div className="example-prompts" role="group" aria-label="예시 질문">
            {EXAMPLE_QUESTIONS.map((ex) => (
              <button key={ex.text} className="example-btn" disabled={blocked} onClick={() => onSendExample(ex.text)} title={ex.text}>
                <span className="example-category">{ex.kind === '견적' ? '견적 예시' : '품셈 상담'}</span>
                <span className="example-question">{ex.text}</span>
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
              {turn.role === 'notice' ? (
                <p className="chat-thread-notice" role="note">{turn.text}</p>
              ) : turn.role === 'user' ? (
                <UserQuestion text={turn.text ?? ''} disabled={blocked} onResend={onResendMessage}
                  failed={!!turn.failed} onRetry={turn.failed && i === turns.length - 1 && onRetry ? () => onRetry(turn) : undefined} />
              ) : (
                <div className="assistant-body">
                  {turn.response && (
                    <AssistantCard
                      ordinal={turns.slice(0, i + 1).filter(item => item.role === 'assistant').length}
                      ratingUserId={ratingUserId}
                      onRatingSaved={onRatingSaved}
                      response={turn.response}
                      elapsedMs={turn.elapsedMs}
                      receivedAtMs={turn.receivedAtMs}
                      interactive={i === turns.length - 1}
                      draft={i === turns.length - 1 ? draft : NO_DRAFT}
                      onSelect={handleSelect}
                      onSubmit={handleSubmitAnswers}
                      loading={blocked}
                      onChangeConditions={(conditions) => onChangeConditions(turn.id, conditions)}
                    />
                  )}
                </div>
              )}
            </div>
          ))}
          {generating && (
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
          {expired && (
            <div className="message"><div className="chat-expired-notice" role="alert">
              <strong>이 대화는 더 이어갈 수 없어요.</strong>
              <p>서버에 보관하던 임시 대화가 만료되었어요(24시간 경과 또는 서버 재시작). 위의 기록은 이 화면에만 남아 있고, 이전 조건과 견적은 서버에 없어 이어서 계산할 수 없어요.</p>
              <button type="button" disabled={loading} onClick={onRecover}>새 대화로 이어서 질문하기</button>
            </div></div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="input-area">{renderInputBox()}<p className="composer-note">견적은 참고용 초안입니다. 사용 전 산출근거를 확인해 주세요.</p></div>
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
              <button className={!props.activeConversationId && !props.restoring ? 'chat-nav-active' : undefined} aria-current={!props.activeConversationId && !props.restoring ? 'page' : undefined} disabled={props.loading} onClick={newChat}><ChatIcon name="plus" />새 대화</button>
            </nav>
            {!!props.conversations?.length && <nav className="chat-history" aria-label="이전 대화"><h2>대화</h2>{props.conversations.map(chat => <ChatHistoryItem key={chat.id} id={chat.id} title={chat.title} active={chat.id === props.activeConversationId} disabled={props.loading}
              onSelect={() => { setOpenSource(null); props.onSelectConversation?.(chat.id); if (window.innerWidth < 900) setSidebarOpen(false); }}
              onDelete={() => props.onDeleteConversation?.(chat.id)} onRename={props.onRenameConversation ? () => props.onRenameConversation?.(chat.id) : undefined} />)}</nav>}
            <div className="chat-sidebar-bottom">
              <button className="chat-sidebar-action" onClick={props.onSettings}><ChatIcon name="settings" />설정</button>
              <button className="chat-sidebar-action" onClick={props.onFeedback}><ChatIcon name="feedback" />피드백 남기기</button>
              {props.accountLabel ? <AccountMenu name={props.accountLabel} usage={props.usage} busy={props.logoutBusy || props.loading} error={props.logoutError} onLogout={props.onLogout} /> : <div className="chat-sidebar-login">
                <strong>품셈이와 함께 시작하세요</strong>
                <div className="chat-guest-usage" role="status" aria-live="polite">
                  {props.authLoading ? '로그인 확인 중…' : !props.usage ? '남은 무료 이용 횟수 확인 중…'
                    : props.usage.service_remaining === 0 ? '오늘 서비스 전체 한도에 도달했어요.'
                    : props.usage.remaining === 0 ? '오늘 무료 이용을 모두 사용했어요.'
                    : <>오늘 남은 무료 이용 · <strong>{props.usage.remaining}회</strong></>}
                </div>
                <p>로그인하면 하루 20회까지 이용할 수 있어요.</p>
                <button disabled={props.authLoading || props.loading} onClick={props.onLogin}>{props.authLoading ? '로그인 확인 중…' : '로그인'}</button>
              </div>}
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

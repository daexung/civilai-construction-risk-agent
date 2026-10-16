import React, { useEffect, useMemo, useState } from 'react';
import {
  AnalyzeResponse, EstimateResponse, TrialItem, TrialState,
  analyze, answerCommon, answerItem, confirmEdit, confirmScope, downloadEstimate, editItem, estimate, health, invalidateTrial, searchItem,
} from '../multiTradeTrialApi';
import './MultiTradeTrial.css';

type ScopeOption = { value: string; label: string };
const SCOPE_OPTIONS: Record<string, ScopeOption[]> = {
  requested: [{ value: 'include_work', label: '시공 작업으로 포함' }, { value: 'exclude_work', label: '이번 견적에서 제외' }],
  excluded: [{ value: 'keep_excluded', label: '제외 요청 유지' }, { value: 'include_work', label: '시공 작업으로 포함' }],
  background: [{ value: 'keep_background', label: '바탕면으로 확인' }],
  condition: [{ value: 'keep_condition', label: '조건으로 확인' }],
  unconfirmed: [
    { value: 'include_work', label: '시공 작업으로 확인' },
    { value: 'exclude_work', label: '이번 견적에서 제외' },
    { value: 'keep_condition', label: '조건으로 확인' },
    { value: 'keep_background', label: '바탕면으로 확인' },
  ],
};
const STATUS_LABEL: Record<string, string> = {
  SCOPE_CONFIRMATION_REQUIRED: '범위 확인 필요', ITEMS_READY: '항목별 검색 대기', ITEMS_IN_PROGRESS: '항목별 진행 중',
  SEARCH_INCOMPLETE: '검색 미완료', CACHE_MISS: '질의 캐시 없음', UNAVAILABLE: '검색 자료 오류',
  COMPLETE_SEARCH: '검색 완료', NOT_STARTED: '검색 대기',
  NEEDS_INPUT: '조건 답변 필요', CALCULATED: '품 산출 완료', UNSUPPORTED: '지원하지 않는 작업',
  NOT_FOUND: '후보 없음', ERROR: '계산 오류', BLOCKED: '추가 확인 필요',
  COMPLETE: '견적 산정 완료', PARTIAL: '부분 산정', PENDING: '항목 계산 대기',
  NEEDS_COMMON: '공통 조건 확인 필요', NO_RESULT: '산정 금액 없음', RATE_VERSION_CONFLICT: '가격 기준 충돌',
};
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

function labelStatus(value?: string) { return value ? STATUS_LABEL[value] || value : '대기'; }
function labelSearchStatus(value?: string) {
  return value === 'COMPLETE' ? STATUS_LABEL.COMPLETE_SEARCH : labelStatus(value);
}
function answerKey(itemId: string, question: Record<string, any>) {
  return `${itemId}:${question.question_id}:${question.version}`;
}
function statusClass(value?: string) { return (value || 'pending').toLowerCase().replace(/[^a-z0-9_-]/g, '-'); }
function won(value: unknown) {
  return typeof value === 'number' ? `${new Intl.NumberFormat('ko-KR').format(value)}원` : '미산정';
}

export default function MultiTradeTrial() {
  const [healthInfo, setHealthInfo] = useState<Record<string, any> | null>(null);
  const [text, setText] = useState('');
  const [analysisRun, setAnalysisRun] = useState<AnalyzeResponse | null>(null);
  const [decisions, setDecisions] = useState<Record<string, string>>({});
  const [workNames, setWorkNames] = useState<Record<string, string>>({});
  const [trial, setTrial] = useState<TrialState | null>(null);
  const [summary, setSummary] = useState<EstimateResponse | null>(null);
  const [basisDate, setBasisDate] = useState(today);
  const [answerValues, setAnswerValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [quantityEdits, setQuantityEdits] = useState<Record<string, string>>({});

  useEffect(() => { health().then(setHealthInfo).catch(() => setHealthInfo(null)); }, []);
  const scopeSpans = useMemo(() => analysisRun?.analysis.scope_spans ?? [], [analysisRun]);
  const scopeComplete = useMemo(() => scopeSpans.length > 0 && scopeSpans.every(span => !!decisions[span.span_id]),
    [scopeSpans, decisions]);
  const owner = analysisRun?.owner_token;
  const trialId = analysisRun?.trial_id;

  const invalidate = () => {
    setSummary(null);
    if (trialId && owner) void invalidateTrial(trialId, owner).catch(() => {});
  };

  const changeBasisDate = async (value: string) => {
    setBasisDate(value); setSummary(null); setError('');
    if (!trialId || !owner) return;
    setBusy('invalidate');
    try { await invalidateTrial(trialId, owner); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const runAnalysis = async () => {
    if (!text.trim()) return;
    setBusy('analyze'); setError(''); setNotice(''); setTrial(null); setSummary(null);
    try {
      const next = await analyze(text.trim());
      setAnalysisRun(next); setDecisions({}); setWorkNames({}); setAnswerValues({});
      setNotice('원문을 구절별로 나눴습니다. 각 구절의 용도를 확인한 뒤 계산을 진행하세요.');
    } catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const confirm = async () => {
    if (!analysisRun || !owner || !scopeComplete) return;
    const payload = scopeSpans.map(span => {
      const decision: Record<string, string> = { span_id: span.span_id, action: decisions[span.span_id] };
      if (decision.action === 'include_work' && ['unconfirmed', 'excluded'].includes(span.classification)) {
        const recognized = analysisRun.analysis.work_items.find(task => task.segment_id === span.span_id)?.work;
        decision.work = (workNames[span.span_id] || recognized || span.text || '').trim();
      }
      return decision;
    });
    setBusy('confirm'); setError('');
    try {
      const next = await confirmScope(analysisRun.trial_id, owner, payload);
      setTrial(next); setSummary(null);
      setNotice('확인된 작업만 항목으로 만들었습니다. 각 항목에서 실제 v1 검색을 실행하세요.');
    } catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const doSearch = async (item: TrialItem) => {
    if (!trialId || !owner) return;
    setBusy(`search:${item.item_id}`); setError(''); setSummary(null);
    try { setTrial(await searchItem(trialId, item.item_id, owner)); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const saveQuantity = async (item: TrialItem) => {
    if (!trialId || !owner || item.quantity == null || item.input_revision == null) return;
    setBusy(`edit:${item.item_id}`); setError(''); invalidate();
    try { setTrial(await editItem(trialId, item.item_id, owner, {
      input_revision: item.input_revision,
      quantity: { value: quantityEdits[item.item_id] ?? String(item.quantity.value), unit: item.quantity.unit },
      conditions: {},
    })); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const reconfirmEdit = async (item: TrialItem) => {
    if (!trialId || !owner || item.input_revision == null) return;
    setBusy(`reconfirm:${item.item_id}`); setError('');
    try { setTrial(await confirmEdit(trialId, item.item_id, owner, item.input_revision)); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const submitAnswer = async (item: TrialItem, question: Record<string, any>) => {
    if (!trialId || !owner) return;
    const key = answerKey(item.item_id, question);
    const value = answerValues[key] ?? '';
    if (!value) return;
    let answer: unknown = value;
    if (['true', 'false'].includes(value)) answer = value === 'true';
    setBusy(`answer:${item.item_id}`); setError(''); setSummary(null);
    try {
      setTrial(await answerItem(trialId, item.item_id, owner, {
        question_id: question.question_id, version: question.version, value: answer, unit: question.unit,
      }));
    } catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const runEstimate = async () => {
    if (!trialId || !owner) return;
    setBusy('estimate'); setError('');
    try { setSummary(await estimate(trialId, owner, basisDate)); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const answerShared = async (question: Record<string, any>, value: string) => {
    if (!trialId || !owner) return;
    setBusy('common'); setError('');
    try { setSummary(await answerCommon(trialId, owner, question.field, value)); }
    catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const download = async () => {
    if (!trialId || !owner) return;
    setBusy('download'); setError('');
    try {
      const blob = await downloadEstimate(trialId, owner);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = 'multi-trade-estimate.xlsx';
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    } catch (exc) { setError((exc as Error).message); }
    finally { setBusy(''); }
  };

  const commonQuestions = summary?.common_questions ?? [];
  const summaryReady = !!summary && ['PARTIAL', 'COMPLETE'].includes(summary.status)
    && !!summary.aggregate?.included?.length;
  const publicAmount = summary?.status === 'COMPLETE'
    ? summary.aggregate?.complete_contract_amount
    : summary?.status === 'PARTIAL' ? summary.aggregate?.partial_contract_amount : null;

  return <main className="multi-trial">
    <header className="multi-trial-header">
      <a href="/chat" className="multi-trial-back">품셈이 채팅으로 돌아가기</a>
      <div><p className="multi-trial-kicker">LOCAL ONLY · DEFAULT OFF</p><h1>복수 공종 견적 시험</h1></div>
      <span className={`multi-trial-health ${healthInfo ? 'is-ready' : ''}`} role="status">
        {healthInfo ? '저장된 v1 자료 확인됨' : '로컬 검색 자료 확인 필요'}
      </span>
    </header>
    <div className="multi-trial-banner">
      이 화면은 로컬 임시 세션입니다. 제품 상담의 로그인·사용량·대화 저장과 연결하지 않습니다.
      저장된 pinned release 파일의 실제 하이브리드 검색만 사용하며, 새 임베딩을 만들지 않습니다.
      캐시에 없는 검색어는 검색 미완료로 멈춥니다.
    </div>
    {healthInfo && <div className="multi-trial-provenance" data-testid="trial-search-provenance">
      검색 자산: {healthInfo.release_id} · {healthInfo.chunk_set_id} · 질의 캐시 {healthInfo.query_cache_count}개 · 외부 임베딩 꺼짐 · 운영 DB 경로 미검증
    </div>}
    {error && <div className="multi-trial-alert" role="alert">{error}</div>}
    {notice && <div className="multi-trial-notice" role="status">{notice}</div>}

    <section className="multi-trial-card">
      <h2>1. 견적 요청 입력</h2>
      <label htmlFor="multi-trial-request">공종과 위치·물량·조건을 원문 그대로 입력하세요</label>
      <textarea id="multi-trial-request" value={text} maxLength={2000} rows={4} disabled={!!busy}
        placeholder="예: 콘크리트 타설 1㎥ 품을 확인해 주세요"
        onChange={event => { setText(event.target.value); if (analysisRun) { invalidate(); setAnalysisRun(null); setTrial(null); setDecisions({}); setWorkNames({}); setAnswerValues({}); setNotice('요청 원문이 바뀌어 기존 분석과 견적 결과를 지웠습니다. 다시 분석해 주세요.'); } }} />
      <div className="multi-trial-actions">
        <button type="button" onClick={runAnalysis} disabled={!!busy || !text.trim()}>
          {busy === 'analyze' ? '구절을 나누는 중…' : '요청 분석'}
        </button>
        <small>규칙 기반 분석만 실행합니다. 원격 모델 호출은 없습니다.</small>
      </div>
    </section>

    {analysisRun && <section className="multi-trial-card">
      <h2>2. 범위 구절 확인</h2>
      <p className="multi-trial-help">모든 구절을 직접 선택해야 검색이 열립니다. 작업·바탕·조건·제외 구절을 원문 위치와 함께 확인하세요.</p>
      {analysisRun.analysis.questions?.map((question, index) => <p className="multi-trial-help" key={index}>확인 질문: {question}</p>)}
      <div className="multi-trial-spans">
        {scopeSpans.map((span: Record<string, any>) => {
          const options = SCOPE_OPTIONS[span.classification] ?? SCOPE_OPTIONS.unconfirmed;
          const action = decisions[span.span_id] ?? '';
          const needsWork = action === 'include_work' && ['unconfirmed', 'excluded'].includes(span.classification);
          const evidence = span.text ?? span.evidence?.text ?? '';
          const recognizedWork = analysisRun.analysis.work_items.find(task => task.segment_id === span.span_id)?.work;
          return <div className="multi-trial-span" key={span.span_id}>
            <div><strong>{evidence || '원문 구절'}</strong><small>{span.classification} · {span.reason || '확인 필요'} · {span.start}-{span.end}</small></div>
            <select aria-label={`${evidence} 사용 범위`} value={action}
              disabled={!!busy}
              onChange={event => { setDecisions(current => ({ ...current, [span.span_id]: event.target.value })); setTrial(null); invalidate(); }}>
              <option value="">구절의 용도를 선택하세요</option>
              {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            {needsWork && <label className="multi-trial-work-name">포함할 작업명
              <input value={workNames[span.span_id] ?? recognizedWork ?? evidence}
                disabled={!!busy}
                onChange={event => { setWorkNames(current => ({ ...current, [span.span_id]: event.target.value })); setTrial(null); invalidate(); }} />
              {recognizedWork && <small>인식된 작업 후보: {recognizedWork}. 다른 작업이면 구절을 분리해 확인하세요.</small>}
            </label>}
          </div>;
        })}
      </div>
      {analysisRun.analysis.limitations?.map((item, index) => <p className="multi-trial-help" key={index}>{item}</p>)}
      <button type="button" onClick={confirm} disabled={!scopeComplete || !!busy}>
        {busy === 'confirm' ? '선택을 확인하는 중…' : '선택한 범위 확인'}
      </button>
    </section>}

    {trial && <section className="multi-trial-card">
      <h2>3. 항목별 실제 검색과 조건 확인</h2>
      <p className="multi-trial-help">검색은 확인한 항목 문구로 pinned knowledge-v1 파일을 조회합니다. 항목마다 정확한 질의 임베딩 캐시가 있어야 합니다.</p>
      {trial.items.map(item => <article className="multi-trial-item" key={item.item_id}>
        <div className="multi-trial-item-title">
          <div><strong>{item.task || item.item_id}</strong><small>{item.item_id} · {labelStatus(item.status)}</small>
            <p className="multi-trial-source">요청 구절: {item.request_text || item.source_spans?.map(span => span.text).filter(Boolean).join(' / ') || '원문 정보 없음'}</p>
          </div>
          <button type="button" onClick={() => doSearch(item)} disabled={!!busy || !item.scope_confirmed}>
            {busy === `search:${item.item_id}` ? '검색 중…' : '실제 v1 검색'}
          </button>
        </div>
        {item.search_status && <p className={`multi-trial-search ${statusClass(item.search_status)}`} data-testid="trial-item-search-status">
          검색: {labelSearchStatus(item.search_status)}
          {item.search_info?.query_cache_hit ? ' · 기존 질의 캐시 적중 · 외부 호출 0회' : ''}
          {item.search_info?.method && ` · ${item.search_info.method}`}
        </p>}
        {item.search_message && <p className="multi-trial-alert">{item.search_message}</p>}
        {!!item.candidates?.length && <div className="multi-trial-candidates">
          <strong>실제 검색 후보</strong>
          {item.candidates.map((candidate, index) => <p key={`${candidate.section_no}:${index}`}>
            {candidate.division} {candidate.section_no} · {candidate.section} · {candidate.has_spec ? '계산 명세 있음' : '계산 명세 없음'}
          </p>)}
        </div>}
        {item.selected_specification && <p className="multi-trial-selected">선택 명세: {item.selected_specification.section_no} {item.selected_specification.title}</p>}
        {item.questions?.map(question => {
          const key = answerKey(item.item_id, question);
          const choices: Array<any> = question.choices ?? question.allowed_values ?? [];
          return <div className="multi-trial-question" key={`${question.question_id}:${question.version}`}>
            <label>{question.ask || question.field}
              {choices.length ? <select value={answerValues[key] ?? ''}
                onChange={event => setAnswerValues(current => ({ ...current, [key]: event.target.value }))}>
                <option value="">선택하세요</option>
                {choices.map(choice => <option key={String(choice.value ?? choice)} value={String(choice.value ?? choice)}>
                  {String(choice.label ?? choice.title ?? (choice.value === true ? '예' : choice.value === false ? '아니요' : choice.value ?? choice))}
                </option>)}
              </select> : <span className="multi-trial-answer-input"><input value={answerValues[key] ?? ''}
                inputMode={question.unit ? 'decimal' : 'text'}
                onChange={event => setAnswerValues(current => ({ ...current, [key]: event.target.value }))} /> {question.unit}</span>}
            </label>
            <button type="button" onClick={() => submitAnswer(item, question)} disabled={!!busy || !answerValues[key]}>
              {busy === `answer:${item.item_id}` ? '답을 적용하는 중…' : '이 항목에 답변'}
            </button>
          </div>;
        })}
        {item.labor && <div className="multi-trial-labor">
          <span>품 산출 상태: {labelStatus(item.status)}</span>
          <span>물량: {item.quantity ? `${item.quantity.value} ${item.quantity.unit || ''}` : '확인 필요'}</span>
          <span>산출 근거: {item.evidence?.unit_lines?.length ?? 0}개 내역 · 인용 {item.evidence?.citations?.length ?? 0}건</span>
          {(item.evidence?.unit_lines ?? []).map((line: any, index: number) => <p key={index}>{line.name || line.item || line.code} · {line.quantity ?? line.qty} {line.unit || ''} · {line.source || line.formula || ''}</p>)}
        </div>}
        {item.quantity && item.scope_confirmed && <div className="multi-trial-edit">
          <label>물량 수정 <input inputMode="decimal" value={quantityEdits[item.item_id] ?? String(item.quantity.value)}
            disabled={!!busy} onChange={event => setQuantityEdits(current => ({ ...current, [item.item_id]: event.target.value }))} /> {item.quantity.unit}</label>
          {item.scope_confirmed
            ? <button type="button" onClick={() => saveQuantity(item)} disabled={!!busy || (quantityEdits[item.item_id] ?? String(item.quantity.value)) === String(item.quantity.value)}>수정안 제출</button>
            : <button type="button" onClick={() => reconfirmEdit(item)} disabled={!!busy}>수정 범위 확인</button>}
        </div>}
        {!item.scope_confirmed && item.input_revision != null && <button type="button" onClick={() => reconfirmEdit(item)} disabled={!!busy}>수정 범위 확인</button>}
      </article>)}
      {!trial.items.length && <p>포함된 시공 항목이 없습니다.</p>}
      <div className="multi-trial-estimate-row">
        <label>가격 기준일 <input type="date" value={basisDate} disabled={!!busy} onChange={event => { void changeBasisDate(event.target.value); }} /></label>
        <button type="button" onClick={runEstimate} disabled={!!busy || !trial.items.length}>
          {busy === 'estimate' ? '통합 계산 중…' : '통합 견적 계산'}
        </button>
      </div>
    </section>}

    {summary && <section className="multi-trial-card" data-testid="trial-estimate-result">
      <h2>4. 통합 견적 결과</h2>
      <div className={`multi-trial-result ${statusClass(summary.status)}`}>
        <strong>{labelStatus(summary.status)}</strong>
        <span>직접비: {won(summary.aggregate?.direct_total ?? summary.partial_estimate?.direct_total)}</span>
        <span>{summary.status === 'PARTIAL' ? '부분 도급 참고액' : '도급액'}: {won(publicAmount)}</span>
      </div>
      {(summary.aggregate?.excluded ?? []).length > 0 && <div className="multi-trial-excluded">
        <h3>계산에 포함하지 않은 항목</h3>
        {(summary.aggregate?.excluded ?? []).map((item: any) => <p key={item.item_id}>{item.item_id} · {item.request_text || item.task || ''} · {item.status} · {item.reason}</p>)}
      </div>}
      {summary.items?.map((item: any) => <article className="multi-trial-result-item" key={item.item_id}>
        <strong>{item.item_id} · {item.status}</strong>
        <p>요청: {item.request_text}</p>
        <p>명세: {item.selected_specification?.section_no || '없음'} {item.selected_specification?.title || ''}</p>
        <p>물량: {item.quantity ? `${item.quantity.value} ${item.quantity.unit || ''}` : '확인 필요'}</p>
        <p>품 금액: {won(item.priced?.reference_amounts?.total)}</p>
        {item.priced?.reference_amounts?.subtotals && <p>재료비 {won(item.priced.reference_amounts.subtotals['재료비'])} · 노무비 {won(item.priced.reference_amounts.subtotals['노무비'])} · 경비 {won(item.priced.reference_amounts.subtotals['경비'])}</p>}
        {!!item.not_calculated_scope?.length && <ul>{item.not_calculated_scope.map((reason: any, index: number) => <li key={index}>{reason.name || reason.item}: {reason.reason}</li>)}</ul>}
      </article>)}
      {commonQuestions.map(question => {
        const choices: Array<any> = question.allowed_values ?? [];
        return <label className="multi-trial-common" key={`${question.question_id}:${question.version}`}>
          {question.ask || question.field}
          <select defaultValue="" onChange={event => { if (event.target.value) void answerShared(question, event.target.value); }}>
            <option value="">공통 조건 선택</option>
            {choices.map(choice => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
          </select>
        </label>;
      })}
      <div className="multi-trial-actions">
        <button type="button" onClick={download} disabled={!summaryReady || !!busy}>
          {busy === 'download' ? '엑셀 준비 중…' : '통합 견적 엑셀 내려받기'}
        </button>
        <small>{summary.status === 'PARTIAL' ? '부분 금액은 산정된 항목만 포함합니다.' : '계산이 완료된 최신 결과만 내려받을 수 있습니다.'}</small>
      </div>
    </section>}
  </main>;
}

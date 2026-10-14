import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { authClient, loginDashboardWithGoogle } from './auth';
import { adminApi } from './adminApi';
import './OwnerDashboard.css';

type Tab = 'overview' | 'ratings' | 'runs' | 'feedback';
const labels: Record<string, string> = { completed: '완료', failed: '실패', running: '진행 중', incomplete: '미완료', good: '긍정', bad: '부정', new: '검토 대기', reviewed: '검토 중', resolved: '검토 완료', amount: '금액', evidence: '근거', understanding: '질문 이해', retrieval: '검색·근거', calculation: '계산', explanation: '설명', other: '기타' };
const show = (value: any) => value == null ? '미수집' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
const localDate = (value?: string) => value ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : '기록 없음';

function DataBox({ title, value, hint }: { title: string; value: React.ReactNode; hint?: string }) {
  return <section className="od-card"><div className="od-card-title">{title}</div><strong>{value}</strong>{hint && <small>{hint}</small>}</section>;
}

function JsonBlock({ title, value }: { title: string; value: any }) {
  if (value == null) return <p className="od-muted">{title}: 기록 없음</p>;
  return <details className="od-json"><summary>{title}</summary><pre>{show(value)}</pre></details>;
}

export default function OwnerDashboard() {
  const [sessionState, setSessionState] = useState<'loading' | 'signed-out' | 'signed-in'>('loading');
  const [userId, setUserId] = useState<string | null>(null);
  const [period, setPeriod] = useState('7d');
  const [tab, setTab] = useState<Tab>('overview');
  const [summary, setSummary] = useState<any>(null);
  const [rows, setRows] = useState<any>(null);
  const [selected, setSelected] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [rating, setRating] = useState('');
  const [reason, setReason] = useState('');
  const [reviewStatus, setReviewStatus] = useState('');
  const [runStatus, setRunStatus] = useState('');
  const [agentMode, setAgentMode] = useState('');
  const [feedbackCategory, setFeedbackCategory] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loginStarting, setLoginStarting] = useState(false);
  const [permission, setPermission] = useState<'unknown' | 'denied' | 'allowed'>('unknown');
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const currentUserId = useRef<string | null>(null);
  const detailRequest = useRef(0);
  currentUserId.current = userId;

  useEffect(() => {
    if (!authClient) { setSessionState('signed-out'); return; }
    let active = true;
    authClient.auth.getSession().then(({ data }) => {
      if (active) { setUserId(data.session?.user.id ?? null); setSessionState(data.session ? 'signed-in' : 'signed-out'); }
    });
    const { data: listener } = authClient.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      const nextUserId = session?.user.id ?? null;
      if (nextUserId !== currentUserId.current) {
        detailRequest.current += 1;
        setSummary(null); setRows(null); setSelected(null); setError(''); setPermission('unknown');
      } else if (session) {
        // Token refresh for the same account keeps the view and reloads its data.
        setRefreshKey(value => value + 1);
      }
      setUserId(nextUserId); setSessionState(session ? 'signed-in' : 'signed-out');
    });
    return () => { active = false; listener.subscription.unsubscribe(); };
  }, []);

  const load = useCallback(async (signal: AbortSignal) => {
    if (!userId || sessionState !== 'signed-in') return;
    setBusy(true); setError('');
    try {
      const overview = await adminApi.summary(period, signal);
      if (signal.aborted) return;
      setSummary(overview); setPermission('allowed');
      let result: any = null;
      if (tab === 'ratings') result = await adminApi.ratings({ period, rating: rating || undefined, reason: reason || undefined, review_status: reviewStatus || undefined, page }, signal);
      if (tab === 'runs') result = await adminApi.runs({ period, status: runStatus || undefined, agent_mode: agentMode || undefined, page }, signal);
      if (tab === 'feedback') result = await adminApi.feedback({ period, category: feedbackCategory || undefined, status: reviewStatus || undefined, page }, signal);
      if (!signal.aborted) { setRows(result); setUpdatedAt(new Date()); }
    } catch (err: any) {
      if (signal.aborted) return;
      if (err.status === 401) { setPermission('unknown'); setSessionState('signed-out'); setSummary(null); setRows(null); setSelected(null); }
      else if (err.status === 403) { setPermission('denied'); setSummary(null); setRows(null); setSelected(null); }
      setError(err.message || '자료를 불러오지 못했습니다.');
    } finally { if (!signal.aborted) setBusy(false); }
  }, [userId, sessionState, period, tab, rating, reason, reviewStatus, runStatus, agentMode, feedbackCategory, page]);

  useEffect(() => {
    if (!userId || sessionState !== 'signed-in') { setSummary(null); setRows(null); setSelected(null); return; }
    const controller = new AbortController();
    let timer: number | undefined;
    const refreshIfVisible = () => { if (document.visibilityState === 'visible') void load(controller.signal); };
    void load(controller.signal);
    const schedule = () => {
      if (timer) window.clearInterval(timer);
      if (document.visibilityState === 'visible') timer = window.setInterval(() => void load(controller.signal), 60000);
    };
    schedule(); document.addEventListener('visibilitychange', schedule);
    window.addEventListener('focus', refreshIfVisible);
    return () => { controller.abort(); if (timer) window.clearInterval(timer); document.removeEventListener('visibilitychange', schedule); window.removeEventListener('focus', refreshIfVisible); };
  }, [load, refreshKey, userId, sessionState]);

  const clearDetail = () => { detailRequest.current += 1; setSelected(null); };
  const chooseTab = (next: Tab) => { clearDetail(); setTab(next); setPage(1); setRows(null); setError(''); };
  const changeFilter = (setValue: (value: string) => void, value: string) => { clearDetail(); setValue(value); setPage(1); setRows(null); };
  const changePage = (change: (page: number) => number) => { clearDetail(); setPage(change); setRows(null); };
  const openItem = async (kind: 'rating' | 'feedback' | 'run', id: string) => {
    const controller = new AbortController(); const requestId = ++detailRequest.current; const requestedUserId = userId; setBusy(true); setSelected(null); setError('');
    try {
      const value = kind === 'rating' ? await adminApi.rating(id, controller.signal)
        : kind === 'feedback' ? await adminApi.feedbackDetail(id, controller.signal) : await adminApi.run(id, controller.signal);
      if (detailRequest.current === requestId && currentUserId.current === requestedUserId) setSelected({ kind, value });
    } catch (err: any) { if (detailRequest.current === requestId && currentUserId.current === requestedUserId) setError(err.message || '상세 자료를 불러오지 못했습니다.'); }
    finally { if (detailRequest.current === requestId) setBusy(false); }
  };

  const trendMax = useMemo(() => Math.max(1, ...(summary?.trend ?? []).map((r: any) => Number(r.total))), [summary]);
  if (sessionState === 'loading') return <main className="od-page"><p>로그인 상태를 확인하고 있습니다.</p></main>;
  if (sessionState === 'signed-out') return <main className="od-page"><header className="od-header"><a href="/">품셈이</a><h1>운영자 대시보드</h1></header><section className="od-panel"><h2>로그인이 필요합니다</h2><p>운영자로 등록된 계정으로 로그인해 주세요.</p><button disabled={loginStarting} onClick={() => { setError(''); setLoginStarting(true); void loginDashboardWithGoogle().catch((e: Error) => { setError(e.message); setLoginStarting(false); }); }}>{loginStarting ? 'Google로 이동 중…' : 'Google 로그인'}</button>{error && <p role="alert">{error}</p>}</section></main>;

  return <main className="od-page">
    <header className="od-header"><a href="/">품셈이</a><div><h1>운영자 대시보드</h1><p>실행 상태와 사용자 평가를 확인합니다. 실행 완료는 답변의 정답을 뜻하지 않습니다.</p></div><button className="od-quiet" onClick={() => authClient?.auth.signOut()}>로그아웃</button></header>
    <div className="od-controls"><label>기간 <select value={period} onChange={e => { clearDetail(); setPeriod(e.target.value); setPage(1); setSummary(null); setRows(null); }}><option value="today">오늘</option><option value="7d">최근 7일</option><option value="30d">최근 30일</option></select></label><button onClick={() => setRefreshKey(v => v + 1)} disabled={busy}>{busy ? '불러오는 중…' : '새로고침'}</button><span className="od-muted">한국 시간 · 마지막 갱신 {updatedAt ? localDate(updatedAt.toISOString()) : '—'}</span></div>
    <nav className="od-tabs">{([['overview','요약'],['ratings','답변 평가'],['runs','실행 기록'],['feedback','일반 의견']] as [Tab,string][]).map(([key,label]) => <button key={key} className={tab===key?'active':''} onClick={() => chooseTab(key)}>{label}</button>)}</nav>
    {error && <div className="od-alert" role="alert">{error}{permission === 'denied' && <span> 서버의 ADMIN_USER_IDS 설정이 필요합니다.</span>}</div>}
    {permission === 'denied' && <section className="od-panel"><h2>접근 권한이 없습니다</h2><p>관리자 계정 설정은 서버에서만 관리합니다. 화면의 계정 정보만으로 권한을 부여하지 않습니다.</p></section>}
    {summary && tab === 'overview' && <>
      <p className="od-note">집계 기준: {localDate(summary.start)}부터 {localDate(summary.as_of)}까지, 종료 시각은 제외합니다. 운영 환경 실행만 표시합니다. 실행 로그는 수집을 시작한 이후 자료이며 전체 질문 수가 아닙니다.</p>
      <div className="od-grid">
        <DataBox title="현재 가입자" value={summary.accounts.current} hint={`기간 내 신규 ${summary.accounts.new}명 · 인증 DB의 비익명 계정`} />
        <DataBox title="실행 상태" value={`${summary.runs.total}건`} hint={`완료 ${summary.runs.completed} · 실패 ${summary.runs.failed} · 진행 ${summary.runs.running} · 미완료 ${summary.runs.incomplete}`} />
        <DataBox title="완료 실행 처리 시간" value={`중앙값 ${summary.latency.p50_ms == null ? '미수집' : `${Math.round(summary.latency.p50_ms)} ms`}`} hint={`상위 95% ${summary.latency.p95_ms == null ? '미수집' : `${Math.round(summary.latency.p95_ms)} ms`} · 표본 ${summary.latency.sample_count}건`} />
        <DataBox title="답변 평가" value={`긍정 ${summary.feedback.positive} · 부정 ${summary.feedback.negative}`} hint={`검토 대기 ${summary.feedback.pending} · 평가 전체 ${summary.feedback.total}건 (비율 대신 건수)`} />
        <DataBox title="일반 의견" value={`${summary.general_feedback.total}건`} hint="선택한 기간 내 접수된 의견" />
        <DataBox title="방문 통계" value="연결되지 않음" hint={summary.unavailable?.visits ?? 'PostHog 서버 조회 미연결'} />
      </div>
      <section className="od-panel"><h2>날짜별 실행</h2>{summary.trend.length ? <div className="od-chart">{summary.trend.map((d: any) => <div key={String(d.day)} title={`${d.day}: 전체 ${d.total}, 완료 ${d.completed}, 실패 ${d.failed}`}><div className="od-bar" style={{ height: `${Math.max(4, Number(d.total) / trendMax * 130)}px` }} /><small>{String(d.day).slice(5)}</small></div>)}</div> : <p className="od-muted">표시할 실행 기록이 없습니다.</p>}</section>
      <section className="od-panel"><h2>최근 실패</h2>{summary.recent_failures.length ? <div className="od-list">{summary.recent_failures.map((r: any) => <button className="od-row" key={r.id} onClick={() => openItem('run', r.id)}><span>{localDate(r.started_at)}</span><span>{r.agent_mode}</span><code>{r.id}</code><span>{labels[r.status] ?? r.status} · 로그 {r.capture_status === 'complete' ? '완전' : '부분'}</span></button>)}</div> : <p className="od-muted">이 기간에 기록된 실패가 없습니다.</p>}</section>
    </>}
    {tab !== 'overview' && <section className="od-panel"><div className="od-section-head"><h2>{tab === 'ratings' ? '답변 평가' : tab === 'runs' ? '실행 기록' : '일반 의견'}</h2><div className="od-filters">
      {tab === 'ratings' && <><select value={rating} onChange={e => changeFilter(setRating, e.target.value)}><option value="">전체 평가</option><option value="good">긍정</option><option value="bad">부정</option></select><select value={reason} onChange={e => changeFilter(setReason, e.target.value)}><option value="">전체 이유</option>{['amount','evidence','understanding','other'].map(s=><option key={s} value={s}>{labels[s]}</option>)}</select><select value={reviewStatus} onChange={e => changeFilter(setReviewStatus, e.target.value)}><option value="">전체 검토 상태</option>{['new','reviewed','resolved'].map(s=><option key={s} value={s}>{labels[s]}</option>)}</select></>}
      {tab === 'runs' && <><select value={runStatus} onChange={e => changeFilter(setRunStatus, e.target.value)}><option value="">전체 실행 상태</option>{['completed','failed','running','incomplete'].map(s=><option key={s} value={s}>{labels[s]}</option>)}</select><select value={agentMode} onChange={e => changeFilter(setAgentMode, e.target.value)}><option value="">전체 처리 경로</option>{['graph','tools','unknown'].map(s=><option key={s} value={s}>{s}</option>)}</select></>}
      {tab === 'feedback' && <><select value={reviewStatus} onChange={e => changeFilter(setReviewStatus, e.target.value)}><option value="">전체 상태</option>{['new','reviewed','resolved'].map(s=><option key={s} value={s}>{labels[s]}</option>)}</select><select value={feedbackCategory} onChange={e => changeFilter(setFeedbackCategory, e.target.value)}><option value="">전체 분류</option>{['bug','suggestion','other'].map(s=><option key={s} value={s}>{s}</option>)}</select></>}
    </div></div>
    {!rows && !busy ? <p className="od-muted">자료를 불러옵니다.</p> : rows?.items?.length ? <div className="od-list">{rows.items.map((r: any) => {
      const id = tab === 'ratings' ? r.answer_id : tab === 'runs' ? r.id : r.id;
      return <button className="od-row" key={id} onClick={() => openItem(tab === 'ratings' ? 'rating' : tab === 'runs' ? 'run' : 'feedback', id)}>
        <span>{localDate(r.created_at ?? r.started_at)}</span><span>{tab === 'ratings' ? `${labels[r.rating]} · ${labels[r.reason] ?? ''}` : tab === 'runs' ? `${labels[r.status]} · ${r.agent_mode}` : `${r.category} · ${labels[r.status] ?? r.status}`}</span><code>{tab === 'runs' ? r.id : id}</code><span>{tab === 'ratings' ? `${labels[r.review_status]} · 실행 ${r.run_id ? '연결' : '기록 없음'}` : tab === 'runs' ? `로그 ${r.capture_status === 'complete' ? '완전' : '부분'}` : '선택해 상세 확인'}</span>
      </button>;
    })}</div> : rows ? <p className="od-muted">조건에 맞는 자료가 없습니다.</p> : null}
    {rows && <div className="od-pagination"><span>총 {rows.total}건 · {rows.page}/{Math.max(1, Math.ceil(rows.total / rows.page_size))}쪽</span><button disabled={page<=1} onClick={()=>changePage(p=>p-1)}>이전</button><button disabled={page*rows.page_size>=rows.total} onClick={()=>changePage(p=>p+1)}>다음</button></div>}
    </section>}
    {selected && <section className="od-panel od-detail"><div className="od-section-head"><h2>{selected.kind === 'rating' ? '평가 상세' : selected.kind === 'feedback' ? '일반 의견 상세' : '실행 상세'}</h2><button className="od-quiet" onClick={clearDetail}>닫기</button></div>
      {selected.kind === 'rating' && <><p>평가 {labels[selected.value.rating]} · 이유 {labels[selected.value.reason] ?? '없음'} · 상태 {labels[selected.value.review_status]}</p><JsonBlock title="질문" value={selected.value.question}/><JsonBlock title="답변" value={selected.value.answer}/><JsonBlock title="사용자 의견" value={selected.value.comment}/><JsonBlock title="검토 메모" value={selected.value.review_note}/><JsonBlock title="올바른 근거" value={selected.value.expected_evidence}/><JsonBlock title="평가 사례 기대 결과" value={selected.value.expected_result}/>{selected.value.run ? <RunView run={selected.value.run}/> : <p className="od-muted">당시 실행 기록 없음 (과거 평가 또는 연결되지 않은 기록)</p>}</>}
      {selected.kind === 'feedback' && <><p>{selected.value.category} · {labels[selected.value.status]} · {localDate(selected.value.created_at)}</p><JsonBlock title="의견 내용" value={selected.value.message}/></>}
      {selected.kind === 'run' && <RunView run={selected.value}/>}
    </section>}
    <footer className="od-footer">실행 상태는 시스템 처리 결과이며 답변 정확도 판정이 아닙니다. 평가·로그가 없는 기간은 실제 이용이 없었다는 뜻이 아닐 수 있습니다.</footer>
  </main>;
}

function RunView({ run }: { run: any }) {
  return <><div className="od-run-meta"><span>실행 {run.id}</span><span>답변 {run.answer_id ?? '생성 전 실패/연결 없음'}</span><span>{labels[run.status] ?? run.status}</span><span>로그 {run.capture_status === 'complete' ? '완전' : '부분'}</span><span>{run.agent_mode} · {run.environment ?? '운영'}</span></div><p>시작 {localDate(run.started_at)} · 종료 {localDate(run.finished_at)}</p><JsonBlock title="버전·환경" value={run.versions}/>{run.steps?.length ? <div className="od-steps"><h3>단계 ({run.steps.length})</h3>{run.steps.map((s: any) => <article key={s.id} className="od-step"><header><b>{s.sequence}. {s.step_kind} / {s.name}</b><span>{labels[s.status] ?? s.status} · {s.duration_ms == null ? '시간 미수집' : `${s.duration_ms} ms`}</span></header><small>{localDate(s.started_at)} → {localDate(s.finished_at)}{s.parent_step_id ? ` · 상위 ${s.parent_step_id}` : ''}</small>{s.error_code && <p>오류 {s.error_code} · {s.error_type}</p>}<JsonBlock title="입력 요약" value={s.input_summary}/><JsonBlock title="출력 요약" value={s.output_summary}/><JsonBlock title="호출 메타데이터" value={s.metadata}/></article>)}</div> : <p className="od-muted">단계 기록이 없습니다. 수집 이전 실행이거나 로그가 부분 저장됐을 수 있습니다.</p>}{run.feedback?.map((f:any)=><p key={f.answer_id}>연결 평가: {labels[f.rating]} · {labels[f.review_status]}</p>)}</>;
}

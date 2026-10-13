import React, { useEffect, useRef, useState } from 'react';
import { askTrial, trialPageUrl, trialHealth, TrialAnswerStatus, TrialResponse, TrialSource, TrialValueClaim } from '../localTrialApi';
import './LocalTrial.css';

// 5·5b단계 로컬 시험 화면. 주 배지는 답변 상태(답변 확인·질문 조건 확인 필요·원문 확인 필요…)이고 검색 상태는 접힌 시험 정보에 둔다.
// 정상 답변 근거 / 검토용 원문 / 진단 후보를 구분해 보여 준다. 기본 꺼짐(REACT_APP_LOCAL_TRIAL=on, 경로 /trial).
const EXAMPLES = [
  '건물 기계실 배관 ø100㎜에 건물용 적산열량계를 설치하면 개당 배관공은 몇 인이야?',
  '철판 두께 0.6㎜, 규격 400㎜짜리 스파이럴덕트를 해체하려면 m당 덕트공이 몇 인이야?',
  '폴리머 시멘트 모르타르방수를 바르는데 모르타르 배합은 어느 기준을 따라야 해?',
  '외벽에 방수모르타르를 15㎜ 두께로 바르려는데 ㎡당 미장공은 몇 인 들어?',
  '호퍼스케일 30톤 이상 계량기를 설치하는 품에 기계 설치까지 들어 있어?',
  '나무 높이 2m짜리 관목을 군식으로 심을 때도 표의 일당 시공량을 그대로 적용하면 돼?',
  '접합 품에는 어떤 종류가 있어?',
  '4-1-1 몇 인이야?',
  '스파이럴덕트를 철판 두께 0.5㎜, 규격 250㎜로 해체할 때 m당 보통인부는 몇 인이야?',
  '시멘트 벽돌을 공장에서 제조하는 품은 얼마야?',
  'BIM 모델링 작업은 품이 몇 인이야?',
];

interface Turn { id: number; question: string; response?: TrialResponse; error?: string; }

function SourceBlock({ s, review, related }: { s: TrialSource; review?: boolean; related?: boolean }) {
  const [page, setPage] = useState(false);
  const where = `${s.division ?? ''} ${s.section_no ?? ''} ${s.section_title ?? ''}`.trim();
  const nCited = s.lines.filter(l => l.cited).length;
  return (
    <div className={`lt-source${review ? ' lt-review' : ''}`} data-testid={related ? 'trial-related-source' : review ? 'trial-review-source' : 'trial-source'}>
      <div className="lt-source-head">
        <strong>{where}{s.cited ? <span className="lt-cited"> · 답변에 인용 {nCited}줄</span> : null}</strong>
        <span>{s.kind} · 원문 {s.printed_page ?? '?'}쪽 (PDF {s.pdf_page ?? '?'}쪽)</span>
      </div>
      {s.note && <div className="lt-source-note">{s.note}</div>}
      {s.frame.length > 0 && <div className="lt-frame">{s.frame.join(' / ')}</div>}
      <ul className="lt-lines">
        {s.lines.map(l => (
          <li key={l.n} className={l.cited ? 'lt-cited-line' : l.selected ? 'lt-selected' : undefined} data-cited={l.cited ? 'true' : undefined}>
            {l.cited && <span className="lt-cited-tag">인용 </span>}{l.display ?? l.text}
          </li>
        ))}
      </ul>
      {(s.shared_legend?.length ?? 0) > 0 && (
        <ul className="lt-legend">{s.shared_legend?.map(g => <li key={g.n}>[공동값#{g.n}] {g.text}</li>)}</ul>
      )}
      {s.pdf_page && (
        <button className="lt-link" type="button" onClick={() => setPage(v => !v)}>{page ? '원문 쪽 이미지 닫기' : '원문 쪽 이미지 보기'}</button>
      )}
      {page && s.pdf_page && <img className="lt-page" alt={`원문 PDF ${s.pdf_page}쪽`} src={trialPageUrl(s.pdf_page)} />}
    </div>
  );
}

function generationLabel(r: TrialResponse): string {
  const g = r.generation;
  if (g.source === 'llm') return '서비스 모델이 고른 원문 위치를 코드가 확인하고 인용문을 가져옴';
  if (g.source === 'verified_source') return `원문만 표시(${g.code ?? g.error ?? ''})`;
  if (g.source === 'structural_lookup') return '구조 조회(모델 호출 없음)';
  return '상태 안내 문구';
}

function statusOf(r: TrialResponse): TrialAnswerStatus {
  return r.answer_status ?? (r.status === 'supported' ? 'confirmed' : r.status);
}

function ValueClaims({ claims }: { claims: TrialValueClaim[] }) {
  return (
    <div className="lt-box" data-testid="trial-values"><h4>답변에 쓴 값 — 원문 칸과 맞춰 본 결과</h4>
      <ul>{claims.filter(c => c.declared && c.alignment !== 'condition_boundary').map((c, i) => (
        <li key={i}>
          <strong>{c.value}{c.unit ? ` ${c.unit}` : ''}</strong>
          {c.column_name ? ` · 열 ${c.column_name}` : ''}{c.row_label ? ` · 행 ${c.row_label}` : ''}{c.unit_basis ? ` · ${c.unit_basis}` : ''}
          {(c.conditions?.length ?? 0) > 0 ? ` · 질문 조건 ${c.conditions?.map(k => `${k.number}${k.ok ? ` 확인${k.cell ? `(${k.cell})` : ''}` : ' 불일치'}`).join(', ')}` : ''}
          {c.alignment === 'line_only' ? ' · 열 대응은 같은 줄 확인까지만 했어요' : ''}
        </li>
      ))}</ul>
    </div>
  );
}

function Answer({ r }: { r: TrialResponse }) {
  const a = statusOf(r);
  const seconds = typeof r.timing_ms === 'object' && r.timing_ms ? ` · ${Math.round(r.timing_ms.total / 100) / 10}초` : '';
  const readSources = a === 'condition_unconfirmed' || a === 'source_check_needed';
  // 답변 확인이면 실제로 인용한 원문만 출처로 두고, 같은 문맥에서 함께 읽은 나머지는 접어 둔다(인용 표시와 출처 목록이 일치해야 한다).
  const anyCited = a === 'confirmed' && r.sources.some(s => s.cited);
  const mainSources = anyCited ? r.sources.filter(s => s.cited) : r.sources;
  const otherSources = anyCited ? r.sources.filter(s => !s.cited) : [];
  return (
    <div className={`lt-card lt-${a}`} data-testid="trial-answer" data-status={r.status} data-answer-status={a}>
      <div className="lt-badge" data-status={a}>{r.answer_status_label ?? r.status_label}</div>
      {r.answer_status_reason?.text && <p className="lt-reason">{r.answer_status_reason.text}</p>}
      {r.answer && <p className="lt-answer">{r.answer}</p>}
      {a === 'confirmed' && (r.value_claims ?? []).some(c => c.declared && c.alignment !== 'condition_boundary') && <ValueClaims claims={r.value_claims ?? []} />}
      {r.confirmations.length > 0 && (
        <div className="lt-box"><h4>확인할 것</h4><ul>{r.confirmations.map(c => <li key={c.code}>{c.text}</li>)}</ul></div>
      )}
      {r.reasons.length > 0 && (
        <div className="lt-box"><h4>이렇게 표시한 이유</h4><ul>{r.reasons.map(c => <li key={c.code}>{c.text}</li>)}</ul></div>
      )}
      {r.alternatives.length > 0 && (
        <div className="lt-box"><h4>부문·절 후보 (정답이나 계산 대상으로 정한 것이 아니에요)</h4>
          <ul>{r.alternatives.map((a2, i) => <li key={i}>{a2.division} {a2.number} {a2.title}{a2.pdf_page ? ` · PDF ${a2.pdf_page}쪽` : ''}</li>)}</ul></div>
      )}
      {r.list && r.list.included.length > 0 && (
        <div className="lt-box"><h4>찾은 공종 목록</h4>
          <ul>{r.list.included.map(x => <li key={x.section_id}>{x.division} {x.number} {x.title}</li>)}</ul>
          <p className="lt-small">{r.list.note}</p></div>
      )}
      {r.sources.length > 0 && (
        <div className="lt-group">
          <h4>{readSources ? '읽은 원문 (답변은 확정하지 못했어요 — 아래 원문을 직접 확인해 주세요)' : '출처 (정상 답변 근거)'}</h4>
          {mainSources.map(s => <SourceBlock key={s.id} s={s} />)}
        </div>
      )}
      {otherSources.length > 0 && (
        <details className="lt-related" data-testid="trial-uncited"><summary>함께 읽은 정상 근거 {otherSources.length}개 (답변에는 인용하지 않았어요)</summary>
          {otherSources.map(s => <SourceBlock key={s.id} s={s} related />)}</details>
      )}
      {(r.related?.length ?? 0) > 0 && (
        <details className="lt-related"><summary>함께 읽은 관련 원문 {r.related?.length}개 (확정 답변에는 쓰지 않았어요)</summary>
          {r.related?.map(s => <SourceBlock key={s.id} s={s} review related />)}</details>
      )}
      {r.review_material.length > 0 && (
        <div className="lt-group lt-reviewgroup"><h4>검토용 원문 — 자동 답변·계산에 쓰지 않았어요</h4>
          {r.review_material.map(s => <SourceBlock key={s.id} s={s} review />)}</div>
      )}
      {r.diagnostic.length > 0 && (
        <details className="lt-diag"><summary>참고 후보 {r.diagnostic.length}개 (근거 아님)</summary>
          <ul>{r.diagnostic.map(d => <li key={d.id}>{d.label}{d.why ? ` — ${d.why}` : ''}</li>)}</ul></details>
      )}
      <details className="lt-meta" data-testid="trial-tech">
        <summary>시험 정보 (개발자용 기록)</summary>
        <div>검색 상태: {r.search_status ?? r.status} · 답변 상태: {a}{r.answer_status_reason ? `(${r.answer_status_reason.code})` : ''}</div>
        <div>설명: {generationLabel(r)}{r.generation.model ? ` · 모델 ${r.generation.model}` : ''}{r.generation.latency_ms ? ` · 설명 ${Math.round(r.generation.latency_ms / 100) / 10}초` : ''}
          {r.generation.usage ? ` · 토큰 ${r.generation.usage.prompt_tokens}/${r.generation.usage.output_tokens}` : ''}</div>
        {r.versions && <div>원문 {r.versions.release_id} · 청킹 {r.versions.chunk_set_id} · 정책 {r.versions.policy}{seconds}</div>}
      </details>
    </div>
  );
}

export default function LocalTrial() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<string>('확인 중');
  const seq = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { trialHealth().then(() => setHealth('연결됨')).catch(() => setHealth('서버 꺼짐 또는 시험 옵션 꺼짐')); }, []);
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: 'smooth' }); }, [turns]);
  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const id = ++seq.current;
    setBusy(true); setText('');
    setTurns(t => [...t, { id, question }]);
    try {
      const response = await askTrial(question);
      setTurns(t => t.map(x => x.id === id ? { ...x, response } : x));
    } catch (e) {
      const code = e instanceof Error ? e.message : 'ERROR';
      const error = code === 'TRIAL_DISABLED' ? '로컬 시험 옵션이 꺼져 있어요.' : code === 'NETWORK_ERROR' ? '서버에 연결하지 못했어요.' : '시험 경로에서 오류가 났어요.';
      setTurns(t => t.map(x => x.id === id ? { ...x, error } : x));
    } finally { setBusy(false); }
  };
  return (
    <div className="lt-app">
      <header className="lt-header">
        <h1>품셈이 · 로컬 시험 모드</h1>
        <p>현재 근거 검색 정책으로 질문 → 근거 상태 → 설명·출처를 확인하는 시험 화면이에요. 로컬에서만 동작하고 원격 저장·로그인·사용량 차감을 쓰지 않아요.</p>
        <p className="lt-small">연결 상태: {health}. 견적 계산·공사비 합산은 하지 않아요. 질문 표현이 원문과 글자가 달라 정상 근거도 &apos;확인 필요&apos;로 나올 수 있고, 원문에 없는 대상과 비슷한 표가 있으면 검토용으로만 보여 드려요.</p>
      </header>
      <section className="lt-examples" aria-label="예시 질문">
        {EXAMPLES.map(q => <button key={q} type="button" disabled={busy} onClick={() => send(q)}>{q}</button>)}
      </section>
      <main className="lt-turns" aria-live="polite">
        {turns.map(t => (
          <div key={t.id} className="lt-turn">
            <div className="lt-user">{t.question}</div>
            {t.response ? <Answer r={t.response} /> : t.error ? <div className="lt-card lt-error" role="alert">{t.error}</div> : <div className="lt-card lt-wait">찾는 중이에요…</div>}
          </div>
        ))}
        <div ref={endRef} />
      </main>
      <form className="lt-form" onSubmit={e => { e.preventDefault(); send(text); }}>
        <textarea aria-label="질문" value={text} disabled={busy} maxLength={500} rows={2} placeholder="표준품셈에 대해 질문해 주세요"
          onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text); } }} />
        <button type="submit" disabled={busy || !text.trim()}>{busy ? '찾는 중…' : '보내기'}</button>
      </form>
    </div>
  );
}

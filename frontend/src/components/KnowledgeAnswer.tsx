import React from 'react';
import { ChevronDown } from 'lucide-react';
import type { KnowledgeResult, KnowledgeSource } from '../types';
import './KnowledgeAnswer.css';

const page = (s: KnowledgeSource) => (s.printed_page ? `인쇄 ${s.printed_page}쪽` : `PDF ${s.pdf_page}쪽`);

// 같은 절·같은 쪽에서 나온 조각은 한 카드로 합친다(같은 제목이 여러 번 보이지 않게).
function group(sources: KnowledgeSource[]): KnowledgeSource[] {
  const byKey = new Map<string, KnowledgeSource>();
  for (const s of sources) {
    const key = `${s.division}|${s.section_no}|${s.pdf_page}`;
    const seen = byKey.get(key);
    if (!seen) byKey.set(key, { ...s, lines: [...s.lines] });
    else seen.lines.push(...s.lines.filter(l => !seen.lines.some(x => x.n === l.n && x.text === l.text)));
  }
  return Array.from(byKey.values());
}

function Source({ source, review }: { source: KnowledgeSource; review: boolean }) {
  return <details className="ka-source">
    <summary>
      <span className={`ka-source-tag${review ? ' review' : ''}`}>{review ? '검토용 원문' : '답변 근거'}</span>
      <span className="ka-source-title">{source.division} {source.section_no} {source.section_title}</span>
      <span className="ka-source-page">{page(source)}</span>
      <ChevronDown size={16} className="ka-chevron" aria-hidden />
    </summary>
    <div className="ka-source-body">
      {source.lines.map((line, i) => <p key={`${line.n}-${i}`} className={line.cited ? 'cited' : undefined}>
        {line.cited && <strong>인용 · </strong>}{line.display || line.text}</p>)}
      {source.image_url && <details className="ka-image"><summary>원문 쪽 이미지 보기</summary>
        <img loading="lazy" src={source.image_url} alt={`PDF ${source.pdf_page}쪽 원문`} /></details>}
    </div>
  </details>;
}

export default function KnowledgeAnswer({ result }: { result: KnowledgeResult }) {
  const evidence = group(result.sources || []);
  const evidenceIds = new Set((result.sources || []).map(s => s.id));
  const review = group([...(result.related || []), ...(result.review_material || [])].filter(s => !evidenceIds.has(s.id)));
  return <section className="ka" aria-label="품셈 근거 답변">
    <span className={`ka-status status-${result.answer_status || 'unknown'}`}>{result.answer_status_label}</span>
    <p className="ka-answer">{result.answer}</p>
    {!!result.confirmations?.length && <div className="ka-confirm">
      <strong>확인할 것</strong>
      {result.confirmations.map((c, i) => <p key={i}>{c.text}</p>)}
    </div>}
    {!!result.alternatives?.length && <ul className="ka-list">{result.alternatives.map((a, i) =>
      <li key={i}><b>{a.division} {a.number}</b> {a.title}</li>)}</ul>}
    {result.list && <div className="ka-included"><p>{result.list.note}</p><ul className="ka-list">{result.list.included.map((a, i) =>
      <li key={i}><b>{a.division} {a.number}</b> {a.title}</li>)}</ul></div>}
    {!!(evidence.length || review.length) && <div className="ka-sources">
      {evidence.map(s => <Source key={s.id} source={s} review={false} />)}
      {review.map(s => <Source key={s.id} source={s} review={true} />)}
    </div>}
  </section>;
}

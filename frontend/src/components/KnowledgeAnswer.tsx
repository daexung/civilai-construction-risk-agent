import React from 'react';
import type { KnowledgeResult, KnowledgeSource } from '../types';

function Source({source,review}:{source:KnowledgeSource;review:boolean}) {
  return <details style={{margin:'10px 0',padding:10,border:'1px solid #ddd',borderRadius:8}}>
    <summary>{review ? '검토용 원문 · ' : '답변 근거 · '}{source.division} {source.section_no} {source.section_title} · {source.printed_page ? `인쇄 ${source.printed_page}쪽` : `PDF ${source.pdf_page}쪽`}</summary>
    {source.lines.map(line=><p key={line.n} style={{whiteSpace:'pre-wrap'}}>{line.cited && <strong>인용 · </strong>}{line.display || line.text}</p>)}
    {source.image_url && <details><summary>원문 쪽 이미지 보기</summary><img loading="lazy" src={source.image_url} alt={`PDF ${source.pdf_page}쪽 원문`} style={{maxWidth:'100%'}}/></details>}
  </details>;
}
export default function KnowledgeAnswer({result}:{result:KnowledgeResult}) {
  return <section aria-label="품셈 근거 답변">
    <strong>{result.answer_status_label}</strong>
    <p style={{whiteSpace:'pre-wrap'}}>{result.answer}</p>
    {result.confirmations?.map((c,i)=><p key={i}>{c.text}</p>)}
    {!!result.alternatives?.length && <ul>{result.alternatives.map((a,i)=><li key={i}>{a.division} {a.number} {a.title}</li>)}</ul>}
    {result.list && <div><p>{result.list.note}</p><ul>{result.list.included.map((a,i)=><li key={i}>{a.division} {a.number} {a.title}</li>)}</ul></div>}
    {result.sources?.map(s=><Source key={s.id} source={s} review={false}/>)}
    {[...(result.related||[]),...(result.review_material||[])].filter((s,i,a)=>a.findIndex(t=>t.id===s.id)===i).map(s=><Source key={s.id} source={s} review={true}/>)}
  </section>;
}

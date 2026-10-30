from __future__ import annotations
import json,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
IDENT='2026-정오표1차/공통/6-2-5/기계적이음'; SP=ROOT/'data/drafts/specs/공통/6-2-5.json'; AP=ROOT/'evals/runtime_validation/per-unit-6-2-5-source-bounded-height-rate-audit-2026-10-19.json'
def main():
 spec=json.loads(SP.read_text(encoding='utf-8'))['draft']
 import pymupdf
 pdf=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
 page=pdf[190].get_text('text')
 assert '6-2-5 철근의 기계적 이음' in page and '높이 10m' in page and all(v in page for v in ['0.06','0.15','0.09','0.11','133','744','10%','20%'])
 src={}
 for line in (ROOT/'data/processed/chunks.all.jsonl').read_text(encoding='utf-8').splitlines():
  x=json.loads(line);src[x['chunk_id']]=x['text']
 assert '10m∼20m미만 10%' in src['p191-t1'] and '20m 이상 20%' in src['p191-t1']
 results=[]; expected_rates={'10m 미만':Fraction(1),'10m~20m 미만':Fraction(11,10),'20m 이상':Fraction(6,5)}
 for height,mult in expected_rates.items():
  result=per_unit(spec,{'quantity':'2','rebar_diameter':'35','work_height':height});assert result.get('status')=='computed',(height,result)
  labor={x['name']:Fraction(x['exact']) for x in result['unit_lines'] if x['kind']=='labor'}
  base={'용접공':Fraction('0.06'),'연마공':Fraction('0.15'),'절단공':Fraction('0.09'),'조력공':Fraction('0.11')}
  assert labor=={k:v*mult for k,v in base.items()},(height,labor)
  price=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),{'quantity':'2','rebar_diameter':'35','work_height':height},'2026-10-01')
  assert price.get('status') in ('COMPLETE','PARTIAL'),price
  results.append({'height':height,'labor_totals':{k:str(v) for k,v in labor.items()},'offline_price_status':price['status']})
 blocked=per_unit(spec,{'quantity':'1','rebar_diameter':'36','work_height':'10m 미만'})
 assert blocked.get('status')=='blocked' and '할증' in blocked.get('reason',''),blocked
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 audit={'id':IDENT,'status':'source_bounded_pass','printed_page':135,'physical_page':191,'original_source_cells':6,'height_scenarios':results,'over_35_case':'blocked; cumulative 5% per 3mm rule retained pending exact step application semantics','draft_validation':'pass','rule_scope':'D35 only and exact height table; excludes above-D35 cumulative rule, material prices and other notes'}
 AP.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 idxp=ROOT/'data/drafts/executable.json';idx=json.loads(idxp.read_text(encoding='utf-8'))
 fail=next((x for x in idx['failed'] if x['id']==IDENT),None)
 idx['failed']=[x for x in idx['failed'] if x['id']!=IDENT];idx['executable']=sorted(set(idx['executable'])|{IDENT})
 idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(x) for x in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)]
 idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'status':audit['status'],'failed_reason':fail['reason'] if fail else 'already promoted','height_scenarios':len(results),'unresolved_above35':'blocked','executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},ensure_ascii=False))
if __name__=='__main__':main()

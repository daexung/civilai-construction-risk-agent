from __future__ import annotations
import json,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/기계설비/13-3-2.json'; AP=ROOT/'evals/runtime_validation/per-unit-13-3-2-exact-resource-deduction-audit-2026-10-19.json'; IDENT='2026-정오표1차/기계설비/13-3-2/기기보온'
def main():
 spec=json.loads(SP.read_text(encoding='utf-8'))['draft']; chunks={}
 for ln in (ROOT/'data/processed/chunks.all.jsonl').read_text(encoding='utf-8').splitlines():
  z=json.loads(ln);chunks[z['chunk_id']]=z['text']
 quote='보일러 본체 보온중 Lagging Sheet를 사용하지 않는 경우 함석공 0.173인 특별인부 0.008인을 감한다.'
 assert quote in chunks['p819-t1']
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=doc[818].get_text('text')
 assert '13-3-2 기기보온' in page and all(x in page for x in ['0.01','0.104','0.173','0.02','0.008','함석공','특별인부'])
 common={'equipment_type':'Boiler 본체','thickness_boiler':'60이하','thickness_duct':'35이하','quantity':'1','material_shape':'Blanket','lagging_sheet_made_on_site':False,'finishing_work_required':False,'insulation_layers':'1','outdoor_boiler':False}
 cases=[]
 for sheet_used,expected in [(True,{'용접공':'0.01','보온공':'0.104','함석공':'0.173','특별인부':'0.02'}),(False,{'용접공':'0.01','보온공':'0.104','함석공':'0','특별인부':'0.012'})]:
  inputs={**common,'lagging_sheet_used':sheet_used};r=per_unit(spec,inputs);assert r.get('status')=='computed',(sheet_used,r.get('status'),r.get('reason'))
  actual={x['name']:Fraction(x['exact']) for x in r['unit_lines'] if x['kind']=='labor'}
  assert actual=={k:Fraction(v) for k,v in expected.items()},(actual,expected)
  if not sheet_used:
   for line in r['unit_lines']:
    if line['name'] in ('함석공','특별인부'):
     assert any(c.get('quote')==quote for c in line['citations'])
  price=price_unit(spec,r['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01');assert price.get('status') in ('OK','COMPLETE','PARTIAL'),price
  cases.append({'lagging_sheet_used':sheet_used,'labor_unit_rates':{k:str(v) for k,v in actual.items()},'offline_price_status':price['status']})
 blocked_inputs={**common,'lagging_sheet_used':False,'material_shape':'Block'}
 blocked=per_unit(spec,blocked_inputs);assert blocked.get('status')=='blocked' and '결합 순서' in blocked.get('reason',''),blocked
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 record={'id':IDENT,'status':'source_bounded_pass','physical_page':819,'printed_page':763,'original_rate_cells':4,'source_rule':'exact cited note deducts 0.173 인 for 함석공 and 0.008 인 for 특별인부 when boiler lagging sheet is absent','scenarios':cases,'overlap_case':'blocked because source does not specify combination order with other surcharges','draft_validation':'pass','scope':'boiler 60이하, Blanket, single-layer, no other adjustment; other rates and combination policies remain separately gated'}
 AP.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 ip=ROOT/'data/drafts/executable.json';idx=json.loads(ip.read_text(encoding='utf-8'));fail=next((x for x in idx['failed'] if x['id']==IDENT),None);idx['failed']=[x for x in idx['failed'] if x['id']!=IDENT];idx['executable']=sorted(set(idx['executable'])|{IDENT});idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(z) for z in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)];ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'status':record['status'],'source_cells':4,'cases':len(cases),'overlap':'blocked','executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},ensure_ascii=False))
if __name__=='__main__':main()

from __future__ import annotations
import json,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/기계설비/13-7-13.json';AP=ROOT/'evals/runtime_validation/per-unit-13-7-13-exact-range-surcharge-audit-2026-10-19.json';IDENT='2026-정오표1차/기계설비/13-7-13/Castable_Spray_공사'
BASE={'15':('0.18','0.36'),'25':('0.245','0.490'),'40':('0.336','0.672'),'50':('0.396','0.632'),'65':('0.48','0.96'),'80':('0.576','1.152'),'100':('0.656','1.312')}
def main():
 spec=json.loads(SP.read_text(encoding='utf-8'))['draft']
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=doc[884];page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).save(ROOT/'evals/runtime_validation/source-p885-castable-spray.png');text=page.get_text('text')
 assert '13-7-13 Castable Spray 공사' in text and all(v in text for pair in BASE.values() for v in pair)
 assert '벽, 천장 Spray시는 본 품의 15% 가산한다.' in text and '비계사용시 높이 6∼9m까지 15% 가산' in text and '9m초과' in text
 all_chunks={}
 for l in (ROOT/'data/processed/chunks.all.jsonl').read_text(encoding='utf-8').splitlines():z=json.loads(l);all_chunks[z['chunk_id']]=z['text']
 assert '비계사용시 높이 6∼9m까지 15% 가산' in all_chunks['p885-t1']
 scenarios=[('no-adjustment',False,'기타',False,'5',Fraction(1)),('wall-surcharge',False,'벽/천장',False,'5',Fraction(23,20)),('scaffold-lower-bound',False,'기타',True,'6',Fraction(23,20)),('scaffold-upper-bound',False,'기타',True,'9',Fraction(23,20)),('both-explicit-15-percent-rules',False,'벽/천장',True,'6',Fraction(13,10))]
 cases=[]
 for thickness,(insulation,helper) in BASE.items():
  for name,_,surface,scaffold,height,factor in scenarios:
   inputs={'thickness':thickness,'quantity':'1','surface_type':surface,'scaffold_used':scaffold,'scaffold_height':height}
   r=per_unit(spec,inputs);assert r.get('status')=='computed',(thickness,name,r.get('reason'))
   expected={'보온공':Fraction(insulation)*factor,'특별인부':Fraction(helper)*factor};actual={x['name']:Fraction(x['exact']) for x in r['unit_lines']};assert actual==expected,(thickness,name,actual,expected)
   for line in r['unit_lines']:
    assert any(c.get('internal_id')=='p885-t1' and c.get('row')==line['name'] and c.get('column')==thickness and Fraction(c.get('value'))==Fraction(BASE[thickness][0 if line['name']=='보온공' else 1]) for c in line['citations'])
    if factor!=1: assert line.get('adjustments') and all(any(c.get('quote') for c in a['citations']) for a in line['adjustments'])
   if thickness=='15':
    price=price_unit(spec,r['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
   cases.append({'thickness':thickness,'scenario':name,'expected_unit_rates':{k:str(v) for k,v in expected.items()}})
 blocked=per_unit(spec,{'thickness':'15','quantity':'1','surface_type':'기타','scaffold_used':True,'scaffold_height':'9.1'})
 assert blocked.get('status')=='blocked' and '매 3m 증가' in blocked.get('reason',''),blocked
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 record={'id':IDENT,'status':'pass','physical_page':885,'printed_page':829,'original_rate_cells':14,'calculation_cases':len(cases),'source_range_cases':['6m','9m'], 'combined_surcharge_case':'both explicit 15% rules accumulated to 30% per general rule','over_9m':'blocked; per-3m increase boundary unresolved','offline_prices':'checked on representative thickness-15 routes','draft_validation':'pass','visually_checked_original_page':'evals/runtime_validation/source-p885-castable-spray.png','scope':'all 14 thickness/resource cells, wall/ceiling fixed rate, exact scaffold interval endpoints, additive overlap, and over-9m block'}
 AP.write_text(json.dumps(record|{'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 ip=ROOT/'data/drafts/executable.json';idx=json.loads(ip.read_text(encoding='utf-8'));idx['failed']=[x for x in idx['failed'] if x['id']!=IDENT];idx['executable']=sorted(set(idx['executable'])|{IDENT});idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(x) for x in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)];ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'status':record['status'],'source_cells':14,'cases':len(cases),'over9':'blocked','executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},ensure_ascii=False))
if __name__=='__main__':main()

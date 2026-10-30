from __future__ import annotations
import json,sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/토목/4-4-1.json';AP=ROOT/'evals/runtime_validation/per-unit-4-4-1-exact-two-axis-coefficient-audit-2026-10-19.json';IDENT='2026-정오표1차/토목/4-4-1/분기기부설'
FACTORS={'50㎏':{'#8':'0.70','#10':'0.82','#12':'0.92','#15':'1.15','#18.5':'1.33','#26':'1.56'},'60㎏':{'#8':'0.75','#10':'0.90','#12':'1.00','#15':'1.20','#18.5':'1.39','#26':'1.62'}}
BASE={'궤도공':'9','보통인부':'3','측량중급기술자':'1','크레인':'3','굴착기+부착용집게':'12'}
def main():
 spec=json.loads(SP.read_text(encoding='utf-8'))['draft']
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=doc[403]
 pix=page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False);pix.save(ROOT/'evals/runtime_validation/source-p404-turnout-factor.png')
 text=page.get_text('text');assert '4-4-1 분기기 부설' in text and all(v in text for row in FACTORS.values() for v in row.values())
 assert all(v in text for v in BASE.values())
 chunks={}
 for line in (ROOT/'data/processed/chunks.all.jsonl').read_text(encoding='utf-8').splitlines():
  z=json.loads(line);chunks[z['chunk_id']]=z['text']
 quote='분기기 종류에 따라 다음의 할증을 적용한다.';assert quote in chunks['p404-t0']
 assert len(FACTORS)*len(next(iter(FACTORS.values())))==12
 cases=[];runtime_cells=0
 for rail,row in FACTORS.items():
  for turnout,factor_raw in row.items():
   factor=Fraction(factor_raw);inputs={'quantity':'2','rail_weight':rail,'turnout_type':turnout};r=per_unit(spec,inputs);assert r.get('status')=='computed',(rail,turnout,r.get('reason'))
   rates={line['name']:Fraction(line['exact']) for line in r['unit_lines']};want={k:Fraction(v)*factor for k,v in BASE.items()};assert rates==want,(rail,turnout,rates,want)
   for line in r['unit_lines']:
    cites=line['citations'];assert any(c.get('internal_id')=='p404-t0' and c.get('value')==BASE[line['name']] for c in cites)
    assert any(c.get('internal_id')=='p404-t1' and c.get('row')==rail and c.get('column')==turnout and c.get('value')==factor_raw for c in cites)
    runtime_cells+=2
   price=price_unit(spec,r['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
   cases.append({'rail_weight':rail,'turnout_type':turnout,'factor':factor_raw,'expected_unit_rates':{k:str(v) for k,v in want.items()},'offline_price_status':price['status']})
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 record={'id':IDENT,'status':'pass','physical_page':404,'printed_page':348,'base_rate_cells':5,'factor_cells':12,'original_source_cells':17,'calculation_routes':len(cases),'resource_factor_checks':runtime_cells,'visually_checked_original_page':'evals/runtime_validation/source-p404-turnout-factor.png','source_application_quote':quote,'draft_validation':'pass','offline_prices':'checked for all 12 routes; catalog-dependent statuses are recorded','scope':'all source rail-weight × turnout-type factor cells applied multiplicatively to all five base resource rates'}
 AP.write_text(json.dumps(record|{'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 ip=ROOT/'data/drafts/executable.json';idx=json.loads(ip.read_text(encoding='utf-8'));fail=next((x for x in idx['failed'] if x['id']==IDENT),None);idx['failed']=[x for x in idx['failed'] if x['id']!=IDENT];idx['executable']=sorted(set(idx['executable'])|{IDENT});idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed']);idx['summary']['failure_reasons_top10']=[list(x) for x in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)];ip.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'status':record['status'],'original_cells':17,'routes':len(cases),'executor_source_cell_refs':runtime_cells,'executable':len(idx['executable']),'failed':len(idx['failed']),'unsupported':idx['summary']['skipped_without_compatible_calculator'],'excluded':idx['summary']['excluded_from_execution']},ensure_ascii=False))
if __name__=='__main__':main()

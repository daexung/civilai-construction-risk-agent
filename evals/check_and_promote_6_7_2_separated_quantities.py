from __future__ import annotations
import hashlib, json, sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from backend.agent.tools.source.citation import cite_table
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one
SPEC=ROOT/'data/drafts/specs/공통/6-7-2.json'
AUDIT=ROOT/'evals/runtime_validation/per-unit-6-7-2-separated-manhole-quantities-2026-10-19.json'
PDF=ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
EXPECTED={
'D900':{'특별인부':('0.48','0.25'),'보통인부':('0.23','0.12'),'크레인':('0.98','0.50')},
'D1,200':{'특별인부':('0.64','0.33'),'보통인부':('0.30','0.15'),'크레인':('1.12','0.57')},
'D1,500':{'특별인부':('0.80','0.41'),'보통인부':('0.38','0.19'),'크레인':('1.25','0.64')},
'D1,800':{'특별인부':('0.96','0.46'),'보통인부':('0.48','0.23'),'크레인':('1.44','0.83')}}
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft']
 chunks={}
 for line in (ROOT/'data/processed/chunks.all.jsonl').read_text(encoding='utf-8').splitlines():
  x=json.loads(line);chunks[x['chunk_id']]=x['text']
 source=chunks['p212-t0']; note=chunks['p212-x5']
 assert '기준 (개당)' in source and '연직구체는 1개의 설치기준으로 설치수량에 따라 추가 계상한다' in note
 # Original printed p.156 / physical PDF p.212: exact values appear on the row labels.
 import pymupdf
 doc=pymupdf.open(PDF); page=doc[211]; txt=page.get_text('text')
 assert '6-7-2 조립식 PC맨홀 설치' in txt and '연직구체는 1개의 설치기준' in txt
 cases=[]; cells=0
 for size,trades in EXPECTED.items():
  inputs={'manhole_size':size,'base_top_quantity':'2','vertical_body_quantity':'3'}
  result=per_unit(spec,inputs); assert result.get('status')=='computed',(size,result)
  totals={}; component_values={}
  for line in result['unit_lines']:
   qty=Fraction(3) if line.get('quantity_input')=='vertical_body_quantity' else Fraction(2)
   totals[line['name']]=totals.get(line['name'],Fraction())+Fraction(line['exact'])*qty
   component_values.setdefault(line['name'],[]).append(Fraction(line['exact']))
   citation=line['citations'][0]
   assert Fraction(citation['value'])==Fraction(line['exact']) and citation['pdf_page']==212 and citation['printed_page']==156
   cells+=1
  want={trade:2*Fraction(a)+3*Fraction(b) for trade,(a,b) in trades.items()}
  assert totals==want,(size,totals,want)
  want_components={trade:[Fraction(a),Fraction(b)] for trade,(a,b) in trades.items()}
  assert component_values==want_components,(size,component_values,want_components)
  price=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01')
  assert price.get('status') in ('COMPLETE','PARTIAL'),price
  cases.append({'size':size,'inputs':inputs,'expected_totals':{k:str(v) for k,v in want.items()},'source_line_count':len(result['unit_lines']),'offline_price_status':price['status']})
 validation=validate_one(SPEC,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'))
 assert validation['ok'],validation
 record={'id':spec['id'],'status':'pass','source_page':'physical p.212 / printed p.156','source_cells':24,'calculation_cases':len(cases),'runtime_cited_lines':cells,'cases':cases,'draft_validation':'pass','offline_price':'checked; catalog dependent','rule_scope':'하부구체+상판 수량 및 연직구체 수량의 분리 합산, 네 규격 및 인력/크레인; 별도 계상 항목과 변경 크레인 규격은 미검증/차단','spec_sha256':hashlib.sha256(SPEC.read_bytes()).hexdigest(),'source_chunk_sha256':hashlib.sha256((ROOT/'data/processed/chunks.all.jsonl').read_bytes()).hexdigest()}
 AUDIT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 # Promote only this exact ID after the independent original-cell, runtime, pricing, and validator checks.
 idxp=ROOT/'data/drafts/executable.json'; idx=json.loads(idxp.read_text(encoding='utf-8')); ident=spec['id']
 idx['failed']=[x for x in idx['failed'] if x.get('id')!=ident]
 idx['executable']=sorted(set(idx['executable'])|{ident})
 idx['summary']['executable']=len(idx['executable']);idx['summary']['failed']=len(idx['failed'])
 from collections import Counter
 idx['summary']['failure_reasons_top10']=[list(x) for x in Counter(str(x.get('reason','')) for x in idx['failed']).most_common(10)]
 idxp.write_text(json.dumps(idx,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':ident,'source_cells':24,'cases':len(cases),'status':record['status'],'partition':idx['summary']},ensure_ascii=False))
if __name__=='__main__': main()

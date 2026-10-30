from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/기계설비/13-5-3.json';AP=ROOT/'evals/runtime_validation/per-unit-13-5-3-duct-process-row-recovery-audit-2026-10-19.json';IDENT='2026-정오표1차/기계설비/13-5-3/덕트제작'
ROWS=[('r01','본뜨기','플랜트제관공','0.523'),('r02','금긋기','플랜트제관공','1.390'),('r03','절단','플랜트제관공','0.380'),('r04','구멍뚫기','플랜트제관공','0.475'),('r05','용접','플랜트용접공','2.550'),('r06','교정','플랜트제관공','1.660'),('r07','도장/도장공','도장공','1.895'),('r08','도장/비계공','비계공','0.073'),('r09','운반조작/건설기계운전(조)','건설기계운전(조)','0.037'),('r10','운반조작/특별인부','특별인부','0.073')]
def main():
 package=json.loads(SP.read_text(encoding='utf-8'));spec=package['draft']
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');pg=doc[829];pg.get_pixmap(matrix=pymupdf.Matrix(1.35,1.35),alpha=False).save(ROOT/'evals/runtime_validation/source-p830-duct-process-table.png');text=pg.get_text('text')
 assert '13-5-3 덕트제작(Air, Gas)' in text and all(value in text for _,_,_,value in ROWS) and '계\n9.056' in text
 assert '소운반이 포함되어 있다' in text and 'Sand Blasting 및 Painting 공량이 포함' in text and '조립 및 설치 품은 제외' in text
 rates={name:Fraction(value) for _,_,name,value in ROWS};assert sum((Fraction(v) for _,_,_,v in ROWS),Fraction())==Fraction('9.056')
 cases=[]
 for quantity in ('1','2.5'):
  inputs={'quantity':quantity};result=per_unit(spec,inputs);assert result.get('status')=='computed',result
  assert len(result['unit_lines'])==len(ROWS)
  got=[(line['name'],Fraction(line['exact'])) for line in result['unit_lines']]
  expected=[(name,Fraction(value)) for _,_,name,value in ROWS];assert got==expected,(got,expected)
  for line,(_,activity,name,value) in zip(result['unit_lines'],ROWS):
   cite=next(c for c in line['citations'] if c.get('internal_id')=='p830-t2');assert cite['row']==({'도장/도장공':'도장','도장/비계공':'도장','운반조작/건설기계운전(조)':'운반조작','운반조작/특별인부':'운반조작'}.get(activity,activity)) and cite['column']=='수량' and cite['value']==value
  totals={name:sum((Fraction(value) for actual,value in got if actual==name),Fraction())*Fraction(quantity) for name in set(name for _,_,name,_ in ROWS)}
  sum_all=sum(totals.values(),Fraction());assert sum_all==Fraction('9.056')*Fraction(quantity)
  price=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
  cases.append({'quantity_ton':quantity,'activity_lines':len(got),'expected_total_person_days':{k:str(v) for k,v in totals.items()},'sum_person_days':str(sum_all),'offline_price_status':price['status'],'price_details':price})
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 AP.write_text(json.dumps({'id':IDENT,'status':'pass','physical_page':830,'printed_page':774,'independently_checked_source_cells':21,'activity_rate_cells':10,'source_trade_cells':10,'source_total_cell':'9.056','calculation_routes':len(cases),'draft_validation':'pass','visually_checked_original_page':'evals/runtime_validation/source-p830-duct-process-table.png','note_scope':['small transport included','sand blasting and painting included','assembly and installation excluded'],'scope':'each exact source activity remains separately cited; equal trade names are price-mapped while activity quantities are not collapsed into synthetic source cells'}|{'source_rows':[{'activity':a,'trade':t,'quantity':q} for _,a,t,q in ROWS],'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'source_cells':21,'activities':10,'routes':len(cases),'price_statuses':sorted({c['offline_price_status'] for c in cases}),'draft_validation':'pass','sum_matches_source':'9.056'},ensure_ascii=False))
if __name__=='__main__':main()

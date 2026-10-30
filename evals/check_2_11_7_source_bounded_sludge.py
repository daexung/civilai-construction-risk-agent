from __future__ import annotations
import json,sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/공통/2-11-7.json';AP=ROOT/'evals/runtime_validation/per-unit-2-11-7-source-bounded-sludge-removal-audit-2026-10-19.json';IDENT='2026-정오표1차/공통/2-11-7/슬러지제거'
def main():
 package=json.loads(SP.read_text(encoding='utf-8'));spec=package['draft'];import pymupdf
 page=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')[118];page.get_pixmap(matrix=pymupdf.Matrix(1.4,1.4),alpha=False).save(ROOT/'evals/runtime_validation/source-p119-sludge-removal.png');text=page.get_text('text')
 assert '2-11-7 슬러지 제거' in text and '0.63' in text and '0.2㎥' in text and '1.00' in text and '인력품의 7%로 계상한다' in text and '2.0×1.2×1.2m' in text
 cases=[]
 for count in ('1','3'):
  inp={'quantity':count,'sludge_bin_size':'2.0×1.2×1.2m'};result=per_unit(spec,inp);assert result.get('status')=='computed',result
  by={(l['kind'],l['name']):Fraction(l['exact']) for l in result['unit_lines']};assert by=={('labor','특별인부'):Fraction('0.63'),('equipment','굴착기'):Fraction('1.00')},by
  assert all(any(c.get('pdf_page')==119 for c in l['citations']) for l in result['unit_lines'])
  price=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inp,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
  costs=price.get('cost_lines',[]);cost=next(c for c in costs if c['name']==spec['cost_rules'][0]['name']);assert cost.get('amount_exact') is not None or cost.get('reason'),cost
  cases.append({'quantity_events':count,'unit_lines':[{k:l.get(k) for k in ('kind','name','unit','exact')} for l in result['unit_lines']],'offline_price_status':price['status'],'tool_and_light_equipment_cost':cost})
 outside=per_unit(spec,{'quantity':'1','sludge_bin_size':'2.0×1.2×1.2m 이상'});assert outside.get('status')=='rejected',outside
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 AP.write_text(json.dumps({'id':IDENT,'status':'pass','physical_page':119,'printed_page':63,'independently_checked_resource_cells':2,'source_rules_checked':2,'calculation_routes':len(cases),'outside_standard_bin':'rejected by input domain; no conversion inferred','offline_price_statuses':sorted({c['offline_price_status'] for c in cases}),'draft_validation':'pass','visually_checked_original_page':'evals/runtime_validation/source-p119-sludge-removal.png','cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'resource_cells':2,'routes':len(cases),'7_percent_cost_rule':'priced from offline labor subtotal when complete','validation':'pass','prices':sorted({c['offline_price_status'] for c in cases})},ensure_ascii=False))
if __name__=='__main__':main()

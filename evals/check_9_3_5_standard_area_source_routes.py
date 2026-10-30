from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/토목/9-3-5.json';AP=ROOT/'evals/runtime_validation/per-unit-9-3-5-standard-area-source-audit-2026-10-19.json';IDENT='2026-정오표1차/토목/9-3-5/용지측량'
RATES={'시가지':{'고급기술자':'30','중급기술자':'79','초급기술자':'90','초급기능사(측량)':'61'},'평지':{'고급기술자':'22.5','중급기술자':'59','초급기술자':'68','초급기능사(측량)':'44'},'촌락지':{'고급기술자':'15','중급기술자':'41','초급기술자':'48','초급기능사(측량)':'31'},'구릉지':{'고급기술자':'13','중급기술자':'35','초급기술자':'41','초급기능사(측량)':'28'}}
def main():
 package=json.loads(SP.read_text(encoding='utf-8'));spec=package['draft'];table=next(x for x in spec['tables'] if x['id']=='p507-t1')
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
 for physical in (507,508): doc[physical-1].get_pixmap(matrix=pymupdf.Matrix(1.4,1.4),alpha=False).save(ROOT/f'evals/runtime_validation/source-p{physical}-area-basis.png')
 original=doc[506].get_text('text');calc=doc[507].get_text('text')
 assert '9-3-5 용지측량' in original and '13' in original and '28' in original
 assert '면적이 증감될 때에는' in calc and '그 비율만큼 증감한다' in calc and '25,000㎡' in calc
 cases=[]
 for district,rates in RATES.items():
  for area,mult in [('25000',Fraction(1)),('50000',Fraction(2))]:
   inputs={'district':district,'area':area,'coordinate_method':False,'river_survey':False};result=per_unit(spec,inputs)
   assert result.get('status')=='computed',(district,area,result)
   actual={line['name']:Fraction(line['exact']) for line in result['unit_lines']};expected={name:Fraction(value)/Fraction(25000) for name,value in rates.items()};assert actual==expected,(district,area,actual,expected)
   for line in result['unit_lines']:
    c=next(c for c in line['citations'] if c.get('internal_id')=='p507-t1'); assert c['row']=='계' and Fraction(c['value'])==Fraction(rates[line['name']])
   price=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
   cases.append({'district':district,'area':area,'expected_unit_rates_per_m2':{k:str(v) for k,v in expected.items()},'independent_total_person_days':{k:str(v*Fraction(int(area))) for k,v in expected.items()},'offline_price_status':price['status'],'price_details':price})
 for conditional in ({'coordinate_method':True,'river_survey':False},{'coordinate_method':False,'river_survey':True}):
  result=per_unit(spec,{'district':'시가지','area':'25000',**conditional});assert result.get('status')=='blocked',result
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 record={'id':IDENT,'status':'pass','source_pdf_pages':[507,508],'printed_pages':[451,452],'independently_checked_cells':16,'calculation_routes':len(cases),'draft_validation':'pass','source_basis_quote':'⑦ 본 품은 연장 500m 폭원 50m(도로폭원을 포함) 면적 25,000㎡ ... 표준으로 한 것이다.','source_area_scaling_quote':'면적이 증감될 때에는 그 비율만큼 증감한다.','policy_limits':'coordinate-calculation and river-survey percentage ranges remain blocked','scope':'four exact district total rows × four resource columns; 25,000㎡ and 50,000㎡ cases; no duplicate regional coefficient applied'}
 AP.write_text(json.dumps(record|{'source_rates':RATES,'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'source_cells':16,'routes':len(cases),'price_statuses':sorted({c['offline_price_status'] for c in cases}),'draft_validation':'pass','blocks':'2 range policies retained'},ensure_ascii=False))
if __name__=='__main__':main()

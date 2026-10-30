from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/공통/3-4-8.json';AP=ROOT/'evals/runtime_validation/per-unit-3-4-8-material-specific-daily-crew-audit-2026-10-19.json';IDENT='2026-정오표1차/공통/3-4-8/기초지정'
RATES={'모래지정':{'output':110,'equipment':['굴착기','플레이트 콤팩터']},'자갈지정':{'output':100,'equipment':['굴착기','진동롤러(핸드가이드식)']},'잡석지정':{'output':90,'equipment':['굴착기','진동롤러(핸드가이드식)']}}
def main():
 package=json.loads(SP.read_text(encoding='utf-8'));spec=package['draft']
 assert package['calc_type']=='daily_crew' and spec['quantity_model']['name']=='adjusted_daily_crew'
 import pymupdf
 doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf');page=doc[132]
 page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),alpha=False).save(ROOT/'evals/runtime_validation/source-foundation-bed-p133.png')
 text=page.get_text('text');assert '3-4-8 기초지정' in text and all(v in text for v in ('110','100','90','플레이트 콤팩터','진동롤러(핸드가이드식)'))
 # Six table rows by three material columns, independently checked against the rendered original.
 expected_cells={'시공량':{'모래지정':'110','자갈지정':'100','잡석지정':'90'},'특별인부':{'모래지정':'1','자갈지정':'1','잡석지정':'1'},'보통인부':{'모래지정':'1','자갈지정':'1','잡석지정':'1'},'굴착기':{'모래지정':'1','자갈지정':'1','잡석지정':'1'},'플레이트콤팩터':{'모래지정':'1','자갈지정':'-','잡석지정':'-'},'진동롤러(핸드가이드식)':{'모래지정':'-','자갈지정':'1','잡석지정':'1'}}
 assert spec['tables'][0]['values']==expected_cells
 cases=[]
 for material,src in RATES.items():
  q=str(src['output']*2);inputs={'material_type':material,'quantity':q};result=adjusted_daily_crew(spec,inputs)
  assert result.get('status')=='computed',(material,result)
  days=Fraction(int(q),src['output']);assert Fraction(result['work_days'])==days
  assert {k:Fraction(v) for k,v in result['person_days'].items()}=={'특별인부':days,'보통인부':days}
  assert {k:Fraction(v) for k,v in result['equipment_days'].items()}=={k:days for k in src['equipment']}
  assert {x['name'] for x in result['unit_lines'] if x['kind']=='equipment'}==set(src['equipment'])
  assert len(result['unit_lines'])==2+len(src['equipment'])
  for line in result['unit_lines']:
   assert line['citations'] and any(c.get('internal_id')=='p133-t0' for c in line['citations'])
   if line['kind']=='labor': assert Fraction(line['exact'])==Fraction(1,src['output'])
   else: assert Fraction(line['exact'])==Fraction(8,src['output'])
  priced=price_unit(spec,result['unit_lines'],select_rate_version('2026-10-01'),inputs,'2026-10-01')
  assert priced.get('status') in ('OK','PARTIAL'),priced
  cases.append({'material_type':material,'quantity':q,'independent_work_days':str(days),'labor_person_days':{k:str(days) for k in ('특별인부','보통인부')},'equipment_days':{k:str(days) for k in src['equipment']},'offline_price_status':priced['status'],'price_details':priced})
 bad=adjusted_daily_crew(spec,{'material_type':'모래지정','quantity':'-1'});assert bad.get('status') in ('rejected','unresolvable')
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 record={'id':IDENT,'status':'pass','source_pdf_physical_page':133,'source_pdf_printed_page':77,'independently_checked_table_cells':18,'independent_arithmetic_routes':3,'draft_validation':'pass','source_image':'evals/runtime_validation/source-foundation-bed-p133.png','source_interpretation':'work output spans each material-specific quantity column; trade/equipment counts are rows; dashes exclude equipment from that material route','scope':'basic daily-crew execution and source cell routing; equipment price items remain catalog-dependent and machine operator exclusion is preserved as a source note'}
 AP.write_text(json.dumps(record|{'source_cells':expected_cells,'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'status':'pass','cells':18,'routes':len(cases),'draft_validation':'pass','prices':[c['offline_price_status'] for c in cases]},ensure_ascii=False))
if __name__=='__main__':main()

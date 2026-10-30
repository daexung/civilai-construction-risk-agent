from __future__ import annotations
import json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SP=ROOT/'data/drafts/specs/기계설비/12-1-2.json';AP=ROOT/'evals/runtime_validation/per-unit-12-1-2-instrument-row-unit-routes-2026-10-19.json';IDENT='2026-정오표1차/기계설비/12-1-2/플랜트계기설치'
BASE={'파이프스텐션':'0.37','계기':'0.3','발신기':'0.27','수신기':'0.22','AirSet':'0.22','변환기':'0.25','수동조작기':'0.2','비율설정기':'0.2','기록계':'0.75','현장지시계 | 규격 LG':'0.75','현장지시계 | 규격 LPG, VG':'0.4','현장지시계 | 규격 PG':'0.22','현장지시계 | 규격 TG':'0.15','후로드식액면계':'1.8','측온계':'0.15','분석계 | 규격 적외선식, 자기식':'12.0','MonoMeter':'0.3','Thermocouple':'0.37','Dispressor | 규격 외통식':'3.0','스위치 | 규격 일반각종':'0.22','전자Valve | 규격 소형':'0.1','전자Valve | 규격 대형':'0.3','강압Valve | 규격 소형':'0.1','강압Valve | 규격 대형':'0.3','여과기 | 규격 소형':'0.1','여과기 | 규격 대형':'0.3','조절Valve | 규격 1B':'0.8','조절Valve | 규격 2B':'1.0','조절Valve | 규격 3B':'1.2','조절Valve | 규격 4B':'1.5','ButterflyValve | 규격 200ø':'1.2','ButterflyValve | 규격 300ø':'2.5','ButterflyValve | 규격 400ø':'3.7','ButterflyValve | 규격 500ø':'5.0','Orifice | 규격 200ø 이하':'0.5','Orifice | 규격 201ø∼500ø':'0.7','Orifice | 규격 501ø이상':'1.0','출력Gauge | 규격 공기식':'0.22','CylinderValve':'4.5','탈습장치':'22.5','탁도검출기':'0.4','P - H m e t e r 검출기':'0.4','X-Ray발생장치':'15','α-Ray발생장치':'15','PowerPack':'3','현장조절계 | 규격 일반각종':'0.75','중성자발생장치 | 규격 〃':'15','FLAME DETECTOR':'0.25'}
def main():
 package=json.loads(SP.read_text(encoding='utf-8'));spec=package['draft'];import pymupdf;doc=pymupdf.open(ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf')
 for n in (773,774):doc[n-1].get_pixmap(matrix=pymupdf.Matrix(1.3,1.3),alpha=False).save(ROOT/f'evals/runtime_validation/source-p{n}-instrument-install.png')
 texts={n:doc[n-1].get_text('text') for n in (773,774)}
 assert '12-1-2 플랜트 계기 설치' in texts[773] and '방폭공사시는 본 품의 20%를 가산한다' in texts[774] and 'Loop 시험시는 본 품의 25%를 가산한다' in texts[774]
 assert len(BASE)==48 and set(BASE)==set(next(f for f in spec['inputs'] if f['name']=='instrument_item')['allowed_values'])
 cases=[]
 for item,raw in BASE.items():
  inp={'instrument_item':item,'quantity':'2','is_explosion_proof':False,'is_loop_test':False};r=per_unit(spec,inp);assert r.get('status')=='computed',(item,r)
  assert len(r['unit_lines'])==1 and r['unit_lines'][0]['name']=='계장공'
  line=r['unit_lines'][0];assert Fraction(line['exact'])==Fraction(raw),(item,line['exact'],raw)
  ratecite=next(c for c in line['citations'] if c.get('internal_id') in ('p773-t1','p774-t0') and c.get('value')==raw)
  unitcite=next(c for c in line['citations'] if c.get('column')=='단위')
  unit=spec['quantity_model']['params']['unit_rate_table']['quantity_unit_selector']['values'][item];assert line['unit']==f'인/{unit}'
  price=price_unit(spec,r['unit_lines'],select_rate_version('2026-10-01'),inp,'2026-10-01');assert price.get('status') in ('OK','PARTIAL'),price
  cases.append({'instrument_item':item,'source_rate':raw,'unit':unit,'rate_cell':ratecite,'unit_cell':unitcite,'offline_price_status':price['status']})
 for flag,factor in [('is_explosion_proof',Fraction(6,5)),('is_loop_test',Fraction(5,4))]:
  for item in ('계기','MonoMeter'):
   inp={'instrument_item':item,'quantity':'1','is_explosion_proof':flag=='is_explosion_proof','is_loop_test':flag=='is_loop_test'};r=per_unit(spec,inp);assert r.get('status')=='computed',r;assert Fraction(r['unit_lines'][0]['exact'])==Fraction(BASE[item])*factor
 both=per_unit(spec,{'instrument_item':'계기','quantity':'1','is_explosion_proof':True,'is_loop_test':True});assert both.get('status')=='blocked',both
 validation=validate_one(SP,ROOT/'data/drafts',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert validation['ok'],validation
 AP.write_text(json.dumps({'id':IDENT,'status':'pass','physical_pages':[773,774],'printed_pages':[717,718],'instrument_rate_cells':48,'instrument_unit_cells':48,'source_adjustment_rate_cells':2,'independent_source_cells':98,'base_routes':len(cases),'single_adjustment_routes':4,'combined_adjustment':'blocked; combination policy unspecified','draft_validation':'pass','offline_price_statuses':sorted({c['offline_price_status'] for c in cases}),'visually_checked_original_pages':['evals/runtime_validation/source-p773-instrument-install.png','evals/runtime_validation/source-p774-instrument-install.png'],'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'id':IDENT,'rates':48,'unit_cells':48,'base_routes':48,'single_adjustment_routes':4,'combined':'blocked','validation':'pass','price_statuses':sorted({c['offline_price_status'] for c in cases})},ensure_ascii=False))
if __name__=='__main__':main()

"""Verify exact 9-9-2 row reconstruction and source-scoped basic routes."""
import hashlib,itertools,json,sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS,DEFAULT_DRAFTS_DIR,file_sha256,load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/토목/9-9-2.json';IMAGE=ROOT/'evals/runtime_validation/source-p592-9-9-2.png';AUDIT=ROOT/'evals/runtime_validation/civil-9-9-2-source-rows-audit-2026-10-19.json'
TRADES=('지적기사','지적산업기사','지적기능사')
ROWS={
'자료조사':{'지적기사':'0.04','지적산업기사':'0.05'},'측량계획 및 준비':{'지적기사':'0.04','지적산업기사':'0.02'},'측량준비도 작성':{'지적기사':'0.01','지적산업기사':'0.04'},'현지 측량 준비':{'지적기사':'0.01','지적산업기사':'0.02','지적기능사':'0.01'},'현지 측량':{'지적기사':'0.38','지적산업기사':'0.38','지적기능사':'0.38'},'성과 설명':{'지적기사':'0.05'},'측량성과도 등 측량성과물 작성':{'지적기사':'0.06','지적산업기사':'0.15'},'측량성과 관련서류 작성':{'지적산업기사':'0.02'},'측량성과 검사 요청':{'지적기사':'0.03','지적산업기사':'0.05'},'지적측량 성과도 교부':{'지적기사':'0.03','지적산업기사':'0.01'}}
OUT={'지적기사':'0.44','지적산업기사':'0.40','지적기능사':'0.39'};IN={'지적기사':'0.21','지적산업기사':'0.34'};TOTAL={'지적기사':'0.65','지적산업기사':'0.74','지적기능사':'0.39'}
REGIONS={'면':Fraction('1.00'),'읍':Fraction('1.10'),'동 시':Fraction('1.30'),'동 구':Fraction('1.40')}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 spec=json.loads(SPEC.read_text(encoding='utf-8'))['draft']; tables={t['id']:t for t in spec['tables']}; raw=tables['p592-t0']['values']; cells=[]
 for row,columns in ROWS.items():
  assert raw[row]==columns,(row,raw.get(row),columns)
  for trade,value in columns.items():cells.append({'table':'p592-t0','row':row,'column':trade,'value':value})
 summaries={'소계 | 구분\n작업별 외업':OUT,'소계 | 구분\n작업별 내업':IN,'합계':TOTAL}
 for row,columns in summaries.items():
  assert raw[row]==columns,(row,raw.get(row),columns)
  for trade,value in columns.items():cells.append({'table':'p592-t0','row':row,'column':trade,'value':value})
 assert {k:sum((Fraction(v.get(k,'0')) for v in ROWS.values()),Fraction()) for k in TRADES}=={k:Fraction(OUT[k])+Fraction(IN.get(k,'0')) for k in TRADES}
 assert tables['p592-t1']['values']['계수']=={'0회':'1.0','1회':'1.3','2회이상':'1.2+(0.10×n)'}
 assert tables['p592-t2']['values']['계수']=={'면':'1.00','읍':'1.10','동 시':'1.30','동 구':'1.40'}
 routes=[]
 for indoor,region in itertools.product((False,True),REGIONS):
  result=per_unit(spec,{'parcel_count':'2','area':'1500','region':region,'is_approval_area':False,'is_designated_partition':False,'is_facility_incorporation':indoor});assert result['status']=='computed',(indoor,region,result)
  basis=IN if indoor else TOTAL;expected={trade:Fraction(value)*REGIONS[region] for trade,value in basis.items()};actual={line['name']:Fraction(line['exact']) for line in result['unit_lines']}
  assert actual==expected,(indoor,region,actual,expected)
  assert all(line['unit']=='인·일/필지' for line in result['unit_lines'])
  assert all(any(c.get('internal_id')=='p592-t0' for c in line['citations']) and any(c.get('internal_id')=='p592-t2' for c in line['citations']) for line in result['unit_lines'])
  routes.append({'facility_incorporation':indoor,'region':region,'rates':{k:str(v) for k,v in actual.items()}})
 for name,adjustment,expected_factor in [('approval',{'is_approval_area':True},Fraction(14,10)),('designated',{'is_designated_partition':True},Fraction(13,10))]:
  result=per_unit(spec,{'parcel_count':'2','area':'1500','region':'면','is_approval_area':False,'is_designated_partition':False,'is_facility_incorporation':False,**adjustment});assert result['status']=='computed',result
  assert {x['name']:Fraction(x['exact']) for x in result['unit_lines']}=={k:Fraction(v)*expected_factor for k,v in TOTAL.items()}
 over=per_unit(spec,{'parcel_count':'2','area':'1501','region':'면','is_approval_area':False,'is_designated_partition':False,'is_facility_incorporation':False});assert over['status']=='blocked'
 overlap=per_unit(spec,{'parcel_count':'2','area':'1500','region':'면','is_approval_area':True,'is_designated_partition':True,'is_facility_incorporation':False});assert overlap['status']=='blocked'
 validation=validate_one(SPEC.resolve(),DEFAULT_DRAFTS_DIR.resolve(),load_chunks(DEFAULT_CHUNKS),file_sha256(DEFAULT_CHUNKS));assert validation['ok'],validation
 audit={'id':spec['id'],'status':'visual_row_reconstruction_and_supported_routes_verified','source':{'physical_page':592,'printed_page':536,'image':'evals/runtime_validation/source-p592-9-9-2.png','image_sha256':sha(IMAGE),'visual_review':True,'numeric_table_cells':cells,'table_cell_count':len(cells),'row_sums_independently_recomputed':True,'area_coefficients':tables['p592-t1']['values']['계수'],'regional_coefficients':tables['p592-t2']['values']['계수']},'runtime':{'per_parcel_basis':'1,500㎡ per parcel; two or more parcels, same source rate added per additional parcel','facility_incorporation':'exact inner-work subtotal row selected','routes':routes,'approval_surcharge':'40% independently computed','designated_partition_surcharge':'30% independently computed','area_above_1500m2':'blocked pending exact fractional/increment interval rule','both_surcharges':'blocked pending source combination order','validator':validation,'full_rule_verification':False},'not_calculated':spec['not_calculated'],'spec_sha256':sha(SPEC),'per_unit_sha256':sha(ROOT/'backend/agent/tools/calc/per_unit.py')}
 AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'source_cells':len(cells),'routes':len(routes),'single_surcharges':2,'blocked_cases':2,'validator':validation['ok']}))
if __name__=='__main__':main()

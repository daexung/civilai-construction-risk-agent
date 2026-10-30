"""Rebuild repeated trade rows in the 13-6-14 continuation tables."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'data/drafts/specs/기계설비/13-6-14.json'
pkg=json.loads(path.read_text(encoding='utf-8')); draft=pkg['draft']
p874=[
 ('기계기사','12.882'),('(해체)목공','4.706'),('플랜트기계설치공','4.706'),('특별인부','4.706'),
 ('석공','3.294'),('특별인부','2.470'),('플랜트기계설치공','1.176'),('플랜트배관공','1.176'),
 ('산소절단공','0.941'),('플랜트용접공','0.588'),('특별인부','4.706'),('특별인부','4.706'),
 ('특수비계공','4.706'),('플랜트기계설치공','4.706'),('플랜트제관공','2.353'),
 ('시공측량기사','9.412'),('시공측량조수','9.412'),('플랜트기계설치공','9.412'),
 ('플랜트기계설치공','9.412'),('플랜트기계설치공','4.706'),('플랜트용접공','4.706'),
 ('특별인부','14.118'),('시공측량기사','2.353')]
p875=[('시공측량조수','2.353'),('플랜트기계설치공','2.353'),('플랜트기계설치공','2.353'),
 ('특별인부','2.353'),('특수비계공','0.624'),('플랜트기계설치공','1.412'),
 ('산소절단공','0.948'),('특별인부','2.353'),('플랜트전공','3.529'),('특별인부','3.529')]
materials=[('산소 6,000ℓ입','0.5','병'),('아세틸렌 2,100ℓ입','0.05','병'),('용접봉 KSE 4301','7','kg')]
assert len(p874)==23 and len(p875)==10 and len(materials)==3
def make_labor(table_id,page,rows,start):
 values={}; cites=[]; text=[]; aliases=[]; names={}
 for j,(trade,value) in enumerate(rows):
  n=start+j; alias=f'원문행 {n:02d} / {trade}'; aliases.append(alias);names[alias]=trade
  values[alias]={'인/ton':value};cites.append({'table_id':table_id,'row':alias,'column':'인/ton','value':value})
  text.append(f'{alias} | 직종 {trade} | 단위 인/ton | 수량 {value}')
 return {'id':table_id,'role':f'공정별 설치품 원문행 복구 (물리 {page}쪽)',
  'source':f'PDF 물리 {page}쪽 / 인쇄 {page-56}쪽; 병합 공정셀 행순서 기준',
  'unit':'인/ton','values':values,'cite':{'table_id':table_id}},cites,text,aliases,names
t1,c1,l1,a1,n1=make_labor('p874-t1',874,p874,1)
t2,c2,l2,a2,n2=make_labor('p875-t0',875,p875,24)
mv={};cm=[];ml=[]
for i,(name,value,unit) in enumerate(materials,1):
 row=f'원문자재 {i:02d} / {name}';mv[row]={'수량':value}
 cm.append({'table_id':'p875-t1','row':row,'column':'수량','value':value})
 ml.append(f'{row} | 규격·품명 {name} | 단위 {unit}/ton | 수량 {value}')
t3={'id':'p875-t1','role':'소모자재 원문행 복구 (물리 875쪽)',
 'source':'PDF 물리 875쪽 / 인쇄 819쪽; 품명·규격·수량 행순서',
 'unit':'자재/ton','values':mv,'cite':{'table_id':'p875-t1'}}
params={'unit_rate_table':{'table':'p874-t1','trades':a1,'column_input':'인/ton',
 'row_by_trade':{x:x for x in a1},'trade_name_by_trade':n1,
 'resource_units_by_row':{x:{x:'인'} for x in a1}},'quantity_input':'quantity',
 'surcharges':[],'note_adjustments':[],
 'additional_unit_rates':[{'table':'p875-t0','trades':a2,'row_by_trade':{x:x for x in a2},
  'column_by_trade':{x:'인/ton' for x in a2},'quantity_input':'quantity','basis':'인/ton',
  'trade_name_by_trade':n2,'resource_units_by_trade':{x:'인' for x in a2}}],
 'proportional_resource_additions':[],
 'additional_materials':[{'name':name,'table':'p875-t1','row':f'원문자재 {i:02d} / {name}',
   'column':'수량','quantity_input':'quantity','quantity_unit':'ton','basis':'1ton','unit':unit,
   'source':'p875-t1 ton당 소모자재 표',
   'cite':{'table_id':'p875-t1','row':f'원문자재 {i:02d} / {name}','column':'수량','value':value}}
   for i,(name,value,unit) in enumerate(materials,1)]}
draft['tables']=[t1,t2,t3]
draft['quantity_model']={'name':'per_unit','params':params,
 'steps':['p874~875 공정별 설치품 표의 각 원문 행 직종·ton당 수량을 물량에 곱한다.',
          'p875 소모자재 3종을 ton당 원문 수량으로 계상한다.',
          '원문에 별도 검사 요율이 표시되지 않아 추가 요율은 적용하지 않는다.'],
 'source':'PDF 물리 874~875쪽 (인쇄 818~819쪽)',
 'rounding':'단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용'}
draft['blocked']=[];draft['not_calculated']=[]
draft['open_questions']=['공정명은 세로 병합 셀로 표시되어 있다. 복구 계산은 원문 행순서의 직종·수량 연결만 사용하며 공정별 소계를 추정하지 않는다.']
pkg['calc_type']='per_unit';pkg['calc_type_raw']='per_unit'
pkg['calc_type_reason']='원문에 인력 행별 직종·수량과 ton당 자재가 있어 직접 계산 가능; 병합 공정명은 행별로 추정하지 않음.'
pkg['citations']=c1+c2+cm;pkg['open_questions']=draft['open_questions']
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
replace={'p874-t1':('13-6-14 Tainter Gate Guide Metal 설치 / 공정별 설치품 ton당 (물리 874쪽)',l1),
 'p875-t0':('13-6-14 Tainter Gate Guide Metal 설치 / 공정별 설치품 ton당 (물리 875쪽)',l2),
 'p875-t1':('13-6-14 Tainter Gate Guide Metal 설치 / 소모자재 ton당 (물리 875쪽)',ml)}
seen=set()
for ch in chunks:
 if ch.get('chunk_id') in replace:
  ch['text']=replace[ch['chunk_id']][0]+'\n'+'\n'.join(replace[ch['chunk_id']][1])
  ch['structure']='row_sequence_exact_cells';ch['issues']=['공정명 병합셀은 직종·수량 행에 임의 배정하지 않음'];seen.add(ch['chunk_id'])
assert seen==set(replace),seen
cp.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in chunks)+'\n',encoding='utf-8')
print(json.dumps({'labor_rows':len(p874)+len(p875),'materials':len(materials)},ensure_ascii=False))

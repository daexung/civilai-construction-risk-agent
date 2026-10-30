"""Recover task/trade rows collapsed into one dictionary key per source page."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'data/drafts/specs/기계설비/13-6-8.json'
pkg=json.loads(path.read_text(encoding='utf-8'));draft=pkg['draft']
p864=[('기계기사','3.33'),('특별인부','0.098'),('측량사','0.038'),('마킹공','0.077'),('석공','0.047'),('형틀목공','0.1'),('특별인부','0.1'),('플랜트기계설치공','0.2'),('특별인부','0.1'),('산소절단공','0.12'),('플랜트기계설치공','0.12'),('특수비계공','0.335'),('특별인부','0.258'),('인력운반공','0.154'),('형틀목공','0.058'),('특별인부','0.058'),('특수비계공','0.167'),('플랜트기계설치공','0.25'),('특별인부','0.25'),('측량기사','0.038'),('플랜트기계설치공','0.077'),('마킹공','0.038'),('특별인부','0.078'),('특수비계공','0.167'),('측량사','0.064'),('플랜트기계설치공','0.258'),('특별인부','0.258'),('특수비계공','0.67'),('측량사','0.064'),('플랜트기계설치공','0.516'),('특별인부','0.327')]
p865=[('측량사','0.051'),('특수비계공','0.267'),('플랜트기계설치공','0.206'),('마킹공','0.103'),('특별인부','0.154'),('플랜트기계설치공','0.038'),('특별인부','0.019'),('플랜트기계설치공','0.285'),('특별인부','0.193'),('특수비계공','0.035'),('측량사','0.032'),('마킹공','0.129'),('플랜트제관공','0.47'),('특별인부','0.23'),('시험사 1급','1.24'),('특별인부','1.24'),('측량사','0.04'),('특수비계공','0.47'),('플랜트기계설치공','0.36'),('마킹공','0.18'),('특별인부','0.27'),('특수비계공','0.1'),('플랜트기계설치공','0.077'),('측량사','0.038'),('마킹공','0.038'),('특별인부','0.21'),('플랜트기계설치공','0.140'),('특수용접공','0.073'),('특별인부','0.19'),('특수비계공','0.335'),('측량사','0.032'),('마킹공','0.129'),('플랜트기계설치공','0.258'),('특별인부','0.193')]
p866=[('특수비계공','0.267'),('플랜트기계설치공','0.206'),('특별인부','0.206'),('특수비계공','1.167'),('플랜트제관공','0.129'),('특별인부','0.5'),('도장공','1.029'),('산소절단공','0.16'),('특별인부','0.08'),('플랜트용접공','6.355'),('특별인부','3.177'),('플랜트전공','0.66'),('특별인부','0.66')]
materials=[('전기용접봉','9.77','kg'),('탄소봉','3.67','kg'),('산소 6,000ℓ입','0.45','병'),('아세틸렌 2,100ℓ입','0.32','병'),('Grinder 12"ø','0.815','개'),('X-ray Film 65×305','4.9','매'),('Tar Epoxy 2회','405','kg')]
assert (len(p864),len(p865),len(p866),len(materials))==(31,34,13,7)
def build(table_id,page,rows,start):
 values={};cites=[];text=[];trades=[];display={}
 for j,(trade,v) in enumerate(rows):
  row=f'원문행 {start+j:03d} / {trade}';values[row]={'인/ton':v};trades.append(row);display[row]=trade
  cites.append({'table_id':table_id,'row':row,'column':'인/ton','value':v})
  text.append(f'{row} | 직종 {trade} | 단위 인/ton | 수량 {v}')
 return {'id':table_id,'role':f'공정별 설치품 원문행 복구 (물리 {page}쪽)','source':f'PDF 물리 {page}쪽 / 인쇄 {page-56}쪽; 병합 공정 셀 행순서', 'unit':'인/ton','values':values,'cite':{'table_id':table_id}},cites,text,trades,display
t1,c1,l1,a1,n1=build('p864-t0',864,p864,1);t2,c2,l2,a2,n2=build('p865-t0',865,p865,32);t3,c3,l3,a3,n3=build('p866-t0',866,p866,66)
mv={};cm=[];ml=[]
for i,(name,v,u) in enumerate(materials,1):
 row=f'원문자재 {i:02d} / {name}';mv[row]={'수량':v};cm.append({'table_id':'p866-t1','row':row,'column':'수량','value':v});ml.append(f'{row} | 품명·규격 {name} | 단위 {u}/ton | 수량 {v}')
t4={'id':'p866-t1','role':'소모자재 원문행 복구 (물리 866쪽)','source':'PDF 물리 866쪽 / 인쇄 810쪽; 품명·규격·수량','unit':'자재/ton','values':mv,'cite':{'table_id':'p866-t1'}}
params={'unit_rate_table':{'table':'p864-t0','trades':a1,'column_input':'인/ton','row_by_trade':{x:x for x in a1},'trade_name_by_trade':n1,'resource_units_by_row':{x:{x:'인'} for x in a1}},
 'quantity_input':'quantity','surcharges':[],'note_adjustments':[],
 'additional_unit_rates':[{'table':tab,'trades':als,'row_by_trade':{x:x for x in als},'column_by_trade':{x:'인/ton' for x in als},'quantity_input':'quantity','basis':'인/ton','trade_name_by_trade':disp,'resource_units_by_trade':{x:'인' for x in als}} for tab,als,disp in [('p865-t0',a2,n2),('p866-t0',a3,n3)]],
 'proportional_resource_additions':[{'base':'labor_rate_total','factor':'0.07','resource_name':'검사','resource_unit':'인','cite':{'table_id':'p866-t0','row':'검사','column':'산정기준','value':'인력품의 7%'},'source':'p866-t0 검사 행 전체 인력품의 7%'}],
 'additional_materials':[{'name':name,'table':'p866-t1','row':f'원문자재 {i:02d} / {name}','column':'수량','quantity_input':'quantity','quantity_unit':'ton','basis':'1ton','unit':unit,'source':'p866-t1 ton당 소모자재 표','cite':{'table_id':'p866-t1','row':f'원문자재 {i:02d} / {name}','column':'수량','value':v}} for i,(name,v,unit) in enumerate(materials,1)]}
draft['tables']=[t1,t2,t3,t4]
draft['quantity_model']={'name':'per_unit','params':params,'steps':['p864~866 공정별 설치품 원문행의 직종별 인/ton 수량을 설치물량에 곱한다.','검사는 전체 인력품의 7%로 별도 계상한다.','p866 소모자재 7종을 ton당 표기 단위로 계산하며 산소·아세틸렌 병은 원문 용기 기준 그대로 유지한다.'],'source':'PDF 물리 864~866쪽 (인쇄 808~810쪽)','rounding':'단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용'}
draft['blocked']=[];draft['not_calculated']=[]
draft['open_questions']=['공정명은 여러 행에 걸친 병합 셀이다. 계산은 78개 인력 행의 원문 행순서와 직종·수량만 연결하며 공정별 소계는 생성하지 않는다.']
pkg['calc_type']='per_unit';pkg['calc_type_raw']='per_unit';pkg['calc_type_reason']='원문 표의 행별 직종·수량, inspection ratio와 자재를 ton당 직접 계산 가능; 공정별 병합셀 소계는 추정하지 않음.'
pkg['citations']=c1+c2+c3+cm+[{'table_id':'p866-t0','row':'검사','column':'산정기준','value':'인력품의 7%'}];pkg['open_questions']=draft['open_questions']
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
replace={'p864-t0':('13-6-8 Spiral Casing 설치 / 공정별 설치품 ton당 (물리 864쪽)',l1),'p865-t0':('13-6-8 Spiral Casing 설치 / 공정별 설치품 ton당 (물리 865쪽)',l2),'p866-t0':('13-6-8 Spiral Casing 설치 / 공정별 설치품 ton당 (물리 866쪽)',l3+['검사 | 산정기준 인력품의 7%']),'p866-t1':('13-6-8 Spiral Casing 설치 / 소모자재 ton당 (물리 866쪽)',ml)}
seen=set()
for ch in chunks:
 if ch.get('chunk_id') in replace:
  ch['text']=replace[ch['chunk_id']][0]+'\n'+'\n'.join(replace[ch['chunk_id']][1]);ch['structure']='row_sequence_exact_cells';ch['issues']=['공정명 병합 셀의 연결은 행별 소계로 추정하지 않음'];seen.add(ch['chunk_id'])
assert seen==set(replace),seen
cp.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in chunks)+'\n',encoding='utf-8')
print(json.dumps({'labor_rows':78,'material_cells':7,'inspection_rule':'7%'},ensure_ascii=False))

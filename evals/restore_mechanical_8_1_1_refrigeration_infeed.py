"""Rebuild the capacity × work-condition × trade matrix from p.745."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];path=ROOT/'data/drafts/specs/기계설비/8-1-1.json'
pkg=json.loads(path.read_text(encoding='utf-8'));draft=pkg['draft']
capacities=['10','20','30','50','80','100','150','200','300','400','500','600']
conditions=['1회 지하1층','1회 지하2층','1회 지하3층','2회 지하2층','2회 지하3층','소운반 10m 거리내','가조립 설치기초상']
trades=['비계공','특별인부']
rows=[
 ['3','1','3','2','3','2','6','2','7','2','1','-','2','-'],
 ['4','2','4','3','5','3','7','4','10','4','2','-','3','-'],
 ['5','3','5','4','7','4','10','5','12','7','2','-','4','1'],
 ['7','3','7','4','9','5','14','6','16','8','2','1','4','2'],
 ['10','5','12','7','15','7','23','8','28','10','4','1','7','3'],
 ['14','6','16','8','20','8','30','10','36','12','4','2','7','4'],
 ['20','11','24','14','31','14','46','18','57','20','6','3','13','6'],
 ['29','11','32','16','40','16','60','20','72','24','7','4','16','8'],
 ['40','20','44','28','56','28','80','40','90','54','12','6','24','12'],
 ['50','30','56','40','72','40','100','60','112','80','16','8','34','14'],
 ['60','40','70','50','90','50','120','80','140','100','20','10','40','20'],
 ['70','50','84','60','108','60','140','100','169','120','24','12','48','24'],
]
assert len(rows)==len(capacities) and all(len(row)==14 for row in rows)
columns=[f'{cond} {trade}' for cond in conditions for trade in trades]
values={capacity:dict(zip(columns,row)) for capacity,row in zip(capacities,rows)}
table={'id':'p745-t0','role':'냉동기 반입 용량·작업조건별 인력품','source':'PDF 물리 745쪽 / 인쇄 689쪽; 냉동기 U.S. ton × 작업조건 × 직종',
 'unit':'인/대','values':values,'cite':{'table_id':'p745-t0'}}
citations=[{'table_id':'p745-t0','row':capacity,'column':column,'value':value}
 for capacity,row in zip(capacities,rows) for column,value in zip(columns,row)]
excluded=[]
for capacity, conditions_to_exclude in (('10',('소운반 10m 거리내','가조립 설치기초상')),
                                       ('20',('소운반 10m 거리내','가조립 설치기초상')),
                                       ('30',('소운반 10m 거리내',))):
 for cond in conditions_to_exclude:
  excluded.append({'trade':'특별인부','when':{'capacity':capacity,'work_condition':cond},
   'source':'p745-t0 원문 해당 용량·작업조건의 특별인부 셀 대시',
   'cite':{'table_id':'p745-t0','row':capacity,'column':f'{cond} 특별인부','value':'-'}})
draft['tables']=[table]
draft['inputs']=[
 {'name':'capacity','type':'enum','allowed_values':capacities,'unit':'U.S. ton','required':True,
  'ask':'냉동기 용량은 몇 U.S. ton입니까?','source':'p745-t0 냉동기 U.S. ton 행'},
 {'name':'work_condition','type':'enum','allowed_values':conditions,'unit':None,'required':True,
  'ask':'반입 작업의 횟수와 층·작업조건은 무엇입니까?','source':'p745-t0 작업횟수·층별 헤더'},
 {'name':'quantity','type':'positive_rational','allowed_values':'0보다 큰 수','unit':'대','required':True,
  'ask':'반입할 냉동기는 몇 대입니까?','source':'냉동기 반입 대수'}]
rate={'table':'p745-t0','trades':trades,'row_input':'capacity','column_input':'work_condition',
 'trade_in_columns_by_table':{'p745-t0':True},'resource_units':{'비계공':'인','특별인부':'인'},
 }
draft['quantity_model']={'name':'per_unit','params':{'unit_rate_table':rate,'quantity_input':'quantity',
 'excluded_resources':excluded},
 'steps':['용량 행과 작업조건·직종 열이 만나는 인/대 품에 반입 대수를 곱한다.',
          '원문 대시 셀은 해당 용량·작업조건에서 특별인부 수량이 기재되지 않은 것으로 제외한다.',
          '시운전은 포함되고 기초 및 소운반은 별도이며, 선택한 작업조건 열만 산정한다.'],
 'source':'PDF 물리 745쪽 / 인쇄 689쪽 8-1-1 표 및 주 ①~③',
 'rounding':'공통 1-2-8·1-2-1 기본 자릿수 적용'}
draft['blocked']=[];draft['open_questions']=[]
pkg['calc_type']='per_unit';pkg['calc_type_raw']='per_unit';pkg['calc_type_reason']='원문 용량 행과 작업조건별 직종 열이 명시되어 exact table lookup 가능.'
pkg['citations']=citations
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
for c in chunks:
 if c.get('chunk_id')=='p745-t0':
  lines=['8-1-1 냉동기 반입 (용량 U.S. ton; 인/대)', '열 순서: '+' | '.join(columns)]
  lines += [capacity+' | '+' | '.join(row) for capacity,row in zip(capacities,rows)]
  c['text']='\n'.join(lines);c['structure']='capacity_condition_trade_matrix_exact';c['issues']=[];break
else:raise AssertionError('p745-t0 source chunk missing')
cp.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in chunks)+'\n',encoding='utf-8')
print(json.dumps({'capacity_rows':12,'conditions':7,'trades_per_condition':2,'cells':168,'dash_cells':5},ensure_ascii=False))

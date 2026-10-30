"""Restore the lost trade and spray-material source columns for 3-2-12."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];path=ROOT/'data/drafts/specs/유지관리/3-2-12.json'
pkg=json.loads(path.read_text(encoding='utf-8'));draft=pkg['draft']
table={'id':'p973-t0','role':'석면건축자재 해체 인력품','source':'PDF 물리 973쪽 / 인쇄 917쪽; 직종 × 자재유형 교차표',
 'unit':'인/㎡','values':{'석면해체공':{'내장재':'0.120','외장재':'0.045','뿜칠재':'0.5'},
                         '보통인부':{'내장재':'0.017','외장재':'0.011','뿜칠재':'-'}},'cite':{'table_id':'p973-t0'}}
params={'unit_rate_table':{'table':'p973-t0','trades':['석면해체공','보통인부'],
 'column_input':'material_type','row_by_trade':{'석면해체공':'석면해체공','보통인부':'보통인부'},
 'trade_name_by_trade':{'석면해체공':'석면해체공','보통인부':'보통인부'},
 'resource_units_by_row':{'석면해체공':{'석면해체공':'인'},'보통인부':{'보통인부':'인'}},
 'trades_by_conditions':[
  {'when':{'material_type':'내장재'},'trades':['석면해체공','보통인부']},
  {'when':{'material_type':'외장재'},'trades':['석면해체공','보통인부']},
  {'when':{'material_type':'뿜칠재'},'trades':['석면해체공']},
 ],
 'base_rate_multipliers':[{'when':{'material_type':'뿜칠재','spray_surface':'콘크리트면'},'factor':'1.2',
   'cite':{'chunk_id':'p973-x3','quote':'콘크리트면에 부착된 석면 뿜칠재의 해체는 본 품의 20%를 할증하여 적용한다.'},
   'source':'p973-x3 [주] ②'}]},'quantity_input':'quantity'}
draft['tables']=[table]
draft['quantity_model']={'name':'per_unit','params':params,
 'steps':['직종 행과 자재유형 열이 만나는 원문 단가에 해체면적을 곱한다.',
          '뿜칠재가 콘크리트면에 부착된 경우 원문 지시에 따라 해당 뿜칠재 해체품에 20% 할증한다.',
          '뿜칠재 표의 보통인부 대시는 수량 없음으로 보고 해당 경로에서만 제외한다.'],
 'source':'PDF 물리 973쪽 / 인쇄 917쪽 표 및 [주] ②',
 'rounding':'공통 1-2-8·1-2-1 기본 자릿수 적용'}
draft['blocked']=[]
draft['open_questions']=[]
pkg['calc_type']='per_unit';pkg['calc_type_raw']='per_unit'
pkg['calc_type_reason']='표의 직종·자재유형 교차 단가와 원문 조건부 20% 할증을 직접 적용.'
pkg['citations']=[{'table_id':'p973-t0','row':row,'column':col,'value':value}
 for row,cells in table['values'].items() for col,value in cells.items()]
pkg['citations'].append({'chunk_id':'p973-x3','quote':'콘크리트면에 부착된 석면 뿜칠재의 해체는 본 품의 20%를 할증하여 적용한다.'})
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
for c in chunks:
 if c.get('chunk_id')=='p973-t0':
  c['text']="3-2-12 석면건축자재 해체 (㎡당)\n석면해체공 | 단위 인 | 내장재 0.120 | 외장재 0.045 | 뿜칠재 0.5\n보통인부 | 단위 인 | 내장재 0.017 | 외장재 0.011 | 뿜칠재 -"
  c['structure']='exact_trade_by_material_matrix';c['issues']=[]
  break
else:raise AssertionError('source table chunk missing')
cp.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in chunks)+'\n',encoding='utf-8')
print('restored 6 exact labor intersections and a cited 20% concrete-spray multiplier')

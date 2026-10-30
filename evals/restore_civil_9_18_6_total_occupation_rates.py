"""Restore the three profession totals from the source's compact matrix."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];path=ROOT/'data/drafts/specs/토목/9-18-6.json'
pkg=json.loads(path.read_text(encoding='utf-8'));draft=pkg['draft']
values={'합계 / 지적기사':{'인원수':'0.002'},'합계 / 지적산업기사':{'인원수':'0.014'},'합계 / 지적기능사':{'인원수':'0.010'}}
draft['tables']=[{'id':'p622-t0','role':'연속지적도 품질개선(수치) 직종별 합계','source':'PDF 물리 622쪽 / 인쇄 566쪽; 합계 행 직종별 인원수',
 'unit':'인/도곽','values':values,'cite':{'table_id':'p622-t0'}}]
trades=['지적기사','지적산업기사','지적기능사']
params={'unit_rate_table':{'table':'p622-t0','trades':trades,'column_input':'인원수','row_input':'합계',
 'row_by_trade':{t:f'합계 / {t}' for t in trades},'trade_name_by_trade':{t:t for t in trades},
 'resource_units_by_row':{f'합계 / {t}':{t:'인' } for t in trades}},
 'quantity_input':'quantity','surcharges':[],'note_adjustments':[]}
draft['quantity_model']={'name':'per_unit','params':params,
 'steps':['원문 합계 행의 1도곽당 직종별 인원수에 지적도 도곽 수를 곱한다.',
          '괄호 안 수치는 원문 주석의 내업 구분을 보존한다. 표의 외업 소계는 공란이고 합계 행을 직접 사용한다.',
          '기계경비와 재료소모품비는 원문 주석에 따라 별도 계상한다.'],
 'source':'PDF 물리 622쪽 / 인쇄 566쪽 합계 행 및 기타사항 ②',
 'rounding':'공통 1-2-8·1-2-1 기본 자릿수 적용'}
draft['blocked']=[];draft['open_questions']=[]
pkg['calc_type']='per_unit';pkg['calc_type_raw']='per_unit';pkg['calc_type_reason']='원문 합계 행에 직종별 1도곽당 인원수가 명시됨.'
pkg['citations']=[{'table_id':'p622-t0','row':f'합계 / {t}','column':'인원수','value':v} for t,v in zip(trades,['0.002','0.014','0.010'])]
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
for c in chunks:
 if c.get('chunk_id')=='p622-t0':
  c['text']="9-18-6 연속지적도 품질개선(수치) (1도곽당 인원수)\n계획 및 준비 | 지적기사 (0.001)\n자료조사 및 수집 | 지적산업기사 (0.001)\n자료분석 및 기초자료 정비 | 지적산업기사 (0.001)\n공간/속성자료 위상·구조화 수정 | 지적산업기사 (0.010) | 지적기능사 (0.010)\n성과대조 및 협의 | 지적산업기사 (0.002)\n성과납품 | 지적기사 (0.001)\n외업 소계 | 공란\n내업 소계 | 지적기사 (0.002) | 지적산업기사 (0.014) | 지적기능사 (0.010)\n합계 / 지적기사 | 인원수 0.002\n합계 / 지적산업기사 | 인원수 0.014\n합계 / 지적기능사 | 인원수 0.010\n비고 | 괄호는 내업임"
  c['structure']='task_profession_matrix_with_totals';c['issues']=[];break
else:raise AssertionError('p622-t0 source chunk missing')
cp.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in chunks)+'\n',encoding='utf-8')
print('restored three exact total-row profession cells; component rows retained for summation audit')

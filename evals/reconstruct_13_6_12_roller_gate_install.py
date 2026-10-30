"""Restore source-row identity lost when repeated trades collapsed into dict keys."""
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec_path = ROOT / 'data/drafts/specs/기계설비/13-6-12.json'
pkg = json.loads(spec_path.read_text(encoding='utf-8'))
draft = pkg['draft']

# Each tuple follows the physical source table top-to-bottom. Process labels
# are merged vertically in the PDF; row ordinals preserve the exact trade/rate
# cell connection without fabricating a process-to-row association.
p871 = [
    ('기계기사','5.33'), ('목공','0.34'), ('특별인부','0.34'),
    ('플랜트기계설치공','0.17'), ('특별인부','0.17'),
    ('플랜트기계설치공','0.34'), ('특별인부','0.17'),
]
p872 = [
    ('석공','1.15'), ('특별인부','0.86'),
    ('플랜트기계설치공','0.19'), ('플랜트배관공','0.19'),
    ('산소절단공','0.12'), ('플랜트용접공','0.12'), ('특별인부','0.51'),
    ('산소절단공','0.56'), ('플랜트기계설치공','0.56'), ('특별인부','1.12'),
    ('특수비계공','0.79'), ('플랜트기계설치공','0.59'), ('산소절단공','0.29'),
    ('플랜트기계설치공','0.29'), ('플랜트용접공','1.6'), ('특별인부','2.77'),
    ('특수비계공','0.79'), ('플랜트용접공','4.9'), ('측량사','0.59'),
    ('측량조수','0.59'), ('산소절단공','0.59'), ('플랜트기계설치공','1.48'),
    ('특별인부','7.76'), ('산소절단공','0.21'), ('플랜트용접공','1.6'),
    ('특별인부','1.81'), ('측량사','0.29'), ('측량조수','0.29'),
    ('플랜트기계설치공','0.73'), ('특별인부','2.29'), ('도장공','0.067'),
    ('특별인부','0.033'), ('특수비계공','0.22'), ('플랜트기계설치공','0.34'),
    ('산소절단공','0.22'), ('특별인부','0.56'), ('플랜트전공','4.25'),
    ('특별인부','4.25'),
]
materials = [
    ('산소 6,000ℓ입','0.69','병'), ('아세틸렌 2,100ℓ입','0.2','병'),
    ('용접봉','31.05','kg'), ('Tar Epoxy 2회','0.536','ℓ'),
]
assert len(p871) == 7 and len(p872) == 38 and len(materials) == 4

def alias(n, trade):
    return f'원문행 {n:02d} / {trade}'

def labor_table(table_id, page, rows, start):
    values, citations, texts, trades = {}, [], [], []
    for offset, (trade, value) in enumerate(rows):
        row = alias(start + offset, trade)
        values[row] = {'인/ton': value}
        citations.append({'table_id': table_id, 'row': row, 'column': '인/ton', 'value': value})
        texts.append(f'{row} | 직종 {trade} | 단위 인/ton | 수량 {value}')
        trades.append(row)
    return {'id': table_id, 'role': f'공정별 설치품 원문행 복구 (물리 {page}쪽)',
            'source': f'PDF 물리 {page}쪽 / 인쇄 {page-56}쪽; 병합 공정 셀의 행 순서와 직종·수량 셀',
            'unit': '인/ton', 'values': values, 'cite': {'table_id': table_id}}, citations, texts, trades

t1, c1, lines1, trade1 = labor_table('p871-t2', 871, p871, 1)
t2, c2, lines2, trade2 = labor_table('p872-t0', 872, p872, 8)
material_values, cm, material_lines = {}, [], []
for n, (name, value, unit) in enumerate(materials, 1):
    row = f'원문자재 {n:02d} / {name}'
    material_values[row] = {'수량': value}
    cm.append({'table_id':'p873-t0','row':row,'column':'수량','value':value})
    material_lines.append(f'{row} | 규격·품명 {name} | 단위 {unit}/ton | 수량 {value}')
t3 = {'id':'p873-t0','role':'소모자재 원문행 복구 (물리 873쪽)',
      'source':'PDF 물리 873쪽 / 인쇄 817쪽; 자재·규격·수량을 원문 행순서대로 연결',
      'unit':'자재/ton','values':material_values,'cite':{'table_id':'p873-t0'}}

params = {
    'unit_rate_table': {
        'table':'p871-t2','trades':trade1,'column_input':'인/ton',
        'row_by_trade':{r:r for r in trade1},
        'trade_name_by_trade':{r:p871[i][0] for i,r in enumerate(trade1)},
        'resource_units_by_row':{r:{r:'인'} for r in trade1},
    },
    'quantity_input':'quantity','surcharges':[],'note_adjustments':[],
    'additional_unit_rates':[{
        'table':'p872-t0','row_by_trade':{r:r for r in trade2},
        'column_by_trade':{r:'인/ton' for r in trade2},'trades':trade2,
        'quantity_input':'quantity','basis':'인/ton',
        'trade_name_by_trade':{r:p872[i][0] for i,r in enumerate(trade2)},
        'resource_units_by_trade':{r:'인' for r in trade2},
    }],
    'proportional_resource_additions':[],
    'additional_materials':[
        {'name':name,'table':'p873-t0','row':f'원문자재 {n:02d} / {name}','column':'수량',
         'quantity_input':'quantity','quantity_unit':'ton','basis':'1ton','unit':unit,
         'source':'p873-t0 ton당 소모자재 표',
         'cite':{'table_id':'p873-t0','row':f'원문자재 {n:02d} / {name}','column':'수량','value':value}}
        for n,(name,value,unit) in enumerate(materials,1)
    ],
}
draft['tables'] = [t1,t2,t3]
draft['quantity_model'] = {
    'name':'per_unit','params':params,
    'steps':['p871~872 공정별 설치품 표의 각 원문 행에서 직종과 인/ton 셀을 연결해 설치물량을 곱한다.',
             '검사 인력 요율은 설치 표에 별도 기재되지 않아 적용하지 않는다.',
             'p873 소모자재 표의 4개 품목별 ton당 수량을 설치물량에 곱한다.'],
    'source':'PDF 물리 871~873쪽 (인쇄 815~817쪽)',
    'rounding':'단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용',
}
draft['open_questions'] = ['공정명은 원문에서 병합 셀로 표시되어 있다. 계산은 독립 직종·수량 행으로 수행하며 공정별 소계는 생성하지 않는다.']
draft['blocked'] = []
draft['not_calculated'] = []
pkg['calc_type']='per_unit'; pkg['calc_type_raw']='per_unit'
pkg['calc_type_reason']='원문 행순서별 직종·수량과 ton당 자재를 직접 계산하며 공정별 병합 셀 연결은 공정 소계로 추정하지 않음.'
pkg['citations'] = c1+c2+cm
pkg['open_questions']=draft['open_questions']
spec_path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

chunks_path=ROOT/'data/processed/chunks.all.jsonl'
chunks=[json.loads(line) for line in chunks_path.read_text(encoding='utf-8').splitlines()]
replace={'p871-t2':('13-6-12 Roller Gate Guide Metal 설치 / 공정별 설치품 ton당 (물리 871쪽)',lines1),
         'p872-t0':('13-6-12 Roller Gate Guide Metal 설치 / 공정별 설치품 ton당 (물리 872쪽)',lines2),
         'p873-t0':('13-6-12 Roller Gate Guide Metal 설치 / 소모자재 ton당 (물리 873쪽)',material_lines)}
seen=set()
for chunk in chunks:
    if chunk.get('chunk_id') in replace:
        title, rows=replace[chunk['chunk_id']]
        chunk['text']=title+'\n'+'\n'.join(rows)
        chunk['structure']='row_sequence_exact_cells'
        chunk['issues']=['공정명 셀은 원문에서 세로 병합되어 있어 직종·수량 행과 임의 연결하지 않음']
        seen.add(chunk['chunk_id'])
assert seen==set(replace),seen
chunks_path.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in chunks)+'\n',encoding='utf-8')
print(json.dumps({'labor_rows':len(p871)+len(p872),'material_rows':len(materials),
                  'labor_unit_rate_sum':str(sum((Fraction(v) for _,v in p871+p872),Fraction())),
                  'tables':list(replace)},ensure_ascii=False))

"""Restore both labor axes and source-linked operation support additions."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];path=ROOT/'data/drafts/specs/기계설비/12-3-2.json'
pkg=json.loads(path.read_text(encoding='utf-8'));draft=pkg['draft']
draft['inputs']=[
 {'name':'quantity','type':'positive_rational','allowed_values':'0보다 큰 수','unit':'Point','required':True,
  'ask':'설치·점검할 I/O Point는 몇 개입니까?','source':'PDF 물리 778쪽 / 인쇄 722쪽 표 (인/Point)'},
 {'name':'support_period','type':'enum','allowed_values':['지원 없음','3개월','6개월'],'unit':None,'required':True,
  'ask':'준공 후 운영·관리 지원이 필요합니까? 필요하면 기간을 선택해 주세요.','source':'PDF 물리 778쪽 / 인쇄 722쪽 [주] ④'}]
t1={'id':'p778-t1','role':'입·출력장치 설치·점검 인력품','source':'PDF 물리 778쪽 / 인쇄 722쪽; 공정 × 직종 × Point당 인원수',
 'unit':'인/Point','values':{'설치':{'기사':'0.008','계장공':'0.042'},'점검·시험':{'기사':'0.046','계장공':'0.080'}},'cite':{'table_id':'p778-t1'}}
t2={'id':'p778-t2','role':'준공 후 운영·관리 지원 가산율','source':'PDF 물리 778쪽 / 인쇄 722쪽 [주] ④',
 'unit':'%','values':{'가산율':{'3개월':'20%','6개월':'40%'}},'cite':{'table_id':'p778-t2'}}
draft['tables']=[t1,t2]
outputs=[]
for process in ('설치','점검·시험'):
 for trade in ('기사','계장공'):
  outputs.append({'kind':'table_rate_product','name':f'{process} {trade}','resource_kind':'labor',
   'table':'p778-t1','row':process,'column':trade,'quantity_input':'quantity','unit':'인',
   'source':'p778-t1 공정·직종 교차 셀'})
for duration in ('3개월','6개월'):
 for trade in ('기사','계장공'):
  outputs.append({'kind':'table_rate_product','name':f'운영관리지원 {duration} 점검·시험 {trade}','resource_kind':'labor',
   'table':'p778-t1','row':'점검·시험','column':trade,'quantity_input':'quantity','unit':'인',
   'when':{'support_period':duration},
   'multiplier':{'table':'p778-t2','row':'가산율','column_input':'support_period',
                 'column_value_map':{'3개월':'3개월','6개월':'6개월'}},
   'source':'p778-t1 점검·시험 직종별 인원수 × p778-t2 운영관리 지원 가산율'})
draft['quantity_model']={'name':'formula','params':{'outputs':outputs},
 'steps':['설치 및 점검·시험 품은 p778-t1의 직종별 Point당 인원수에 수량을 곱한다.',
          '운영관리 지원이 선택되면 점검·시험 직종별 품에 p778-t2의 기간별 가산율을 곱해 별도 인력으로 더한다.',
          '전선·통신선 및 DDC 외함 설치는 원문 주석에 따라 별도 계상한다.'],
 'source':'PDF 물리 778쪽 / 인쇄 722쪽 표 및 [주] ②~④','rounding':'원문 계수의 정확한 유리수 계산'}
draft['blocked']=[];draft['open_questions']=[]
pkg['calc_type']='formula';pkg['calc_type_raw']='formula';pkg['calc_type_reason']='원문 설치·점검 인력 계수와 기간별 운영관리 가산율을 각각 표 셀에서 조회해 계산.'
pkg['citations']=[{'table_id':'p778-t1','row':r,'column':c,'value':v} for r,c,v in [
 ('설치','기사','0.008'),('설치','계장공','0.042'),('점검·시험','기사','0.046'),('점검·시험','계장공','0.080')]]
pkg['citations'] += [{'table_id':'p778-t2','row':'가산율','column':c,'value':v} for c,v in [('3개월','20%'),('6개월','40%')]]
path.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cp=ROOT/'data/processed/chunks.all.jsonl';chunks=[json.loads(x) for x in cp.read_text(encoding='utf-8').splitlines()]
texts={'p778-t1':('12-3-2 입·출력장치(I/O Equipment) 설치 (인/Point)',[
 '설치 | 기사 0.008 | 계장공 0.042','점검·시험 | 기사 0.046 | 계장공 0.080']),
 'p778-t2':('12-3-2 입·출력장치(I/O Equipment) 설치 운영·관리 지원 가산율',[
 '기간 3개월 | 점검·시험품의 20%','기간 6개월 | 점검·시험품의 40%'])}
seen=set()
for c in chunks:
 if c.get('chunk_id') in texts:
  title,rows=texts[c['chunk_id']];c['text']=title+'\n'+'\n'.join(rows);c['structure']='exact_process_trade_rate_matrix';c['issues']=[];seen.add(c['chunk_id'])
assert seen==set(texts)
cp.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in chunks)+'\n',encoding='utf-8')
print(json.dumps({'labor_source_cells':4,'support_rate_cells':2,'conditional_outputs':4},ensure_ascii=False))

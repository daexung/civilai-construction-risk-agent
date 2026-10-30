"""Connect 7-2-5's explicit standard-area × worst-condition efficiency formula."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'data/drafts/specs/토목/7-2-5.json'
CHUNKS=ROOT/'data/processed/chunks.all.jsonl'
pkg=json.loads(SPEC.read_text(encoding='utf-8'));spec=pkg['draft']
eff_rows={
 '0~15m':{'조용할때':'0.75','풍랑':'0.64','0~2.8km/hr':'0.75','2.8~5.5km/hr':'0.53','보통':'0.75','흐릴때':'0.49'},
 '15~20m':{'조용할때':'0.57','풍랑':'0.48','0~2.8km/hr':'0.57','2.8~5.5km/hr':'0.40','보통':'0.57','흐릴때':'0.37'},
 '20~25m':{'조용할때':'0.41','풍랑':'0.35','0~2.8km/hr':'0.41','2.8~5.5km/hr':'0.29','보통':'0.41','흐릴때':'0.27'},
 '25~30m':{'조용할때':'0.35','풍랑':'0.30','0~2.8km/hr':'0.35','2.8~5.5km/hr':'0.25','보통':'0.35','흐릴때':'0.23'},
}
columns={'tide_condition':['천후|조용할때','천후|풍랑'],'current_speed':['조류|0~2.8km/hr','조류|2.8~5.5km/hr'],'visibility':['명암|보통','명암|흐릴때']}
table={'id':'p447-t1','role':'작업효율(E): 수심 × 천후·조류·명암 조건','source':'PDF 447쪽 7-2-5 작업효율 표','unit':'무차원','values':{}}
for depth,row in eff_rows.items():
 table['values'][depth]={columns['tide_condition'][i]:row[columns['tide_condition'][i].split('|')[1]] for i in range(2)}
 table['values'][depth].update({columns['current_speed'][i]:row[columns['current_speed'][i].split('|')[1]] for i in range(2)})
 table['values'][depth].update({columns['visibility'][i]:row[columns['visibility'][i].split('|')[1]] for i in range(2)})
table['cite']={'table_id':'p447-t1'}
spec['tables']=[spec['tables'][0],table]
old={x['name']:x for x in spec['inputs']}
spec['inputs']=[old['gorgi_type'],
 {'name':'depth_band','type':'enum','allowed_values':list(eff_rows),'unit':'m','required':True,'ask':'수심은 원문 효율표의 어느 구간입니까?','source':'PDF 447쪽 p447-t1 수심 행'},
 {'name':'tide_condition','type':'enum','allowed_values':columns['tide_condition'],'unit':None,'required':True,'ask':'천후 조건은 조용할 때와 풍랑 중 어느 쪽입니까?','source':'PDF 447쪽 p447-t1 천후 열'},
 {'name':'current_speed','type':'enum','allowed_values':columns['current_speed'],'unit':'km/hr','required':True,'ask':'조류 속도는 어느 원문 구간입니까?','source':'PDF 447쪽 p447-t1 조류 열'},
 {'name':'visibility','type':'enum','allowed_values':columns['visibility'],'unit':None,'required':True,'ask':'명암 조건은 보통과 흐릴 때 중 어느 쪽입니까?','source':'PDF 447쪽 p447-t1 명암 열'}]
spec['inputs'].append({'name':'monthly_workdays_20plus','type':'boolean','allowed_values':[True,False],'unit':None,'required':True,'ask':'천후 조건에서 월 20일 정도 작업일수를 확보할 수 있습니까?','source':'PDF 447쪽 p447-x11 [주] ②'})
derived=[]
derived.append({'kind':'table_cell','name':'standard_area_multiplier','cases':[{'table':'p447-t0','row':'표준고르기면적(a)','column_input':'gorgi_type'}]})
for name,inp,colprefix in [('tide_efficiency','tide_condition','천후'),('current_efficiency','current_speed','조류'),('visibility_efficiency','visibility','명암')]:
 derived.append({'kind':'table_cell','name':name,'cases':[{'table':'p447-t1','row_input':'depth_band','column_input':inp}]})
derived[1]['cases']=[
 {'when':{'monthly_workdays_20plus':True},'value':'1.00','unit':'무차원','source':'PDF 447쪽 [주] ②','cite':{'chunk_id':'p447-x11','quote':'천후는 월간 20일 정도의 작업일수를 취할 수 있을 경우 1.00으로 한다.'}},
 {'when':{'monthly_workdays_20plus':False},'table':'p447-t1','row_input':'depth_band','column_input':'tide_condition'}]
derived.append({'kind':'minimum','name':'worst_efficiency','inputs':['tide_efficiency','current_efficiency','visibility_efficiency'],'source':'PDF 447쪽 [주] ④: 천후·조류·명암 조건 가운데 최악의 경우 하나만 택한다.','unit':'무차원'})
spec['quantity_model']={'name':'formula','params':{'derived':derived,'outputs':[
 {'kind':'formula','name':'시간당 수중고르기 능력 A','resource_kind':'production_rate','unit':'m²/hr','expression':{'mul':[{'input':'standard_area_multiplier'},{'input':'worst_efficiency'}]},'formula':'A = a × min(E천후, E조류, E명암)','source':'PDF 447쪽 1. 작업능력','cite':{'chunk_id':'p447-x1','quote':'A=a×E'}}]},'steps':['p447-t0에서 고르기 종류별 표준고르기면적 a를 조회한다.','p447-t1에서 수심·천후·조류·명암에 해당하는 세 E 값을 조회한다.','원문 [주] ④에 따라 세 조건 중 최소 작업효율 하나를 적용한다.','A = a × E로 시간당 수중고르기 능력을 계산한다.'],'source':'PDF 447쪽 7-2-5 작업능력 및 효율 표','rounding':'원문 표 수치 그대로 유리수로 계산하며 중간 반올림하지 않는다.'}
spec['rules']=['천후·조류·명암 중 가장 불리한 조건의 작업효율 하나를 적용한다.','선박 및 부장장비 손료와 운전경비는 별도 계상한다.']
spec['blocked']=[]
pkg['calc_type']='formula';pkg['calc_type_reason']='A=a×E와 E의 원문 표, 최악 조건 선택 규칙이 확인되어 공식 계산기로 실행한다.'
SPEC.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Correct only the saved source table chunk's known omitted cloudy-visibility cells.
lines=CHUNKS.read_text(encoding='utf-8').splitlines();out=[];found=False
for line in lines:
 d=json.loads(line)
 if d.get('chunk_id')=='p447-t1':
  d['structure']='row_header';d['uncertain_record_ids']=[]
  d['text']='7-2-5 수중고르기\n3. 작업효율(E)\n수심 0~15m | 천후 조용할때 0.75 | 천후 풍랑 0.64 | 조류 0~2.8km/hr 0.75 | 조류 2.8~5.5km/hr 0.53 | 명암 보통 0.75 | 명암 흐릴때 0.49\n수심 15~20m | 천후 조용할때 0.57 | 천후 풍랑 0.48 | 조류 0~2.8km/hr 0.57 | 조류 2.8~5.5km/hr 0.40 | 명암 보통 0.57 | 명암 흐릴때 0.37\n수심 20~25m | 천후 조용할때 0.41 | 천후 풍랑 0.35 | 조류 0~2.8km/hr 0.41 | 조류 2.8~5.5km/hr 0.29 | 명암 보통 0.41 | 명암 흐릴때 0.27\n수심 25~30m | 천후 조용할때 0.35 | 천후 풍랑 0.30 | 조류 0~2.8km/hr 0.35 | 조류 2.8~5.5km/hr 0.25 | 명암 보통 0.35 | 명암 흐릴때 0.23'
  found=True
 out.append(json.dumps(d,ensure_ascii=False,separators=(',',':')))
assert found
CHUNKS.write_text('\n'.join(out)+'\n',encoding='utf-8')
import hashlib
pkg['meta']['chunks_sha256']=hashlib.sha256(CHUNKS.read_bytes()).hexdigest()
SPEC.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'reconstructed','table_rows':len(eff_rows),'table_cells':sum(map(len,eff_rows.values())),'omitted_cells_recovered':4,'calc_type':pkg['calc_type']}))

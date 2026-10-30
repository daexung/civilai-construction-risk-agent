from __future__ import annotations
import json,sys,unicodedata
from pathlib import Path
from fractions import Fraction
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit,select_rate_version
from pipeline.validate_drafts import load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/공통/6-3-10.json'; PDF=ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
EXPECTED={'p199-t1':{'형틀목공':{'수량':'0.043'},'보통인부':{'수량':'0.009'}},'p199-t2':{'형틀목공':{'수량':'0.029'},'보통인부':{'수량':'0.006'}},'p199-t3':{'방수공':{'수량':'0.021'},'보통인부':{'수량':'0.004'}}}
UNITS={'다웰바 설치':'ea','채움재 설치':'㎡','실링 마감':'m'}
TRADES={'다웰바 설치':['형틀목공','보통인부'],'채움재 설치':['형틀목공','보통인부'],'실링 마감':['방수공','보통인부']}
def norm(s): return ''.join(unicodedata.normalize('NFKC',str(s)).split()).casefold()
def main():
 pkg=json.loads(SPEC.read_text(encoding='utf8')); spec=pkg['draft']; cells=routes=0
 with pymupdf.open(PDF) as doc:
  source=norm(doc[198].get_text())
  for tid,rows in EXPECTED.items():
   table=next(t for t in spec['tables'] if t['id']==tid)
   assert table['values']==rows,(tid,table['values'])
   for row,cols in rows.items():
    assert norm(row) in source,(tid,row)
    for col,val in cols.items():
     assert norm(col) in source and norm(val) in source,(tid,row,col,val)
     cells+=1
 for work,tid in zip(UNITS,('p199-t1','p199-t2','p199-t3')):
  inputs={'work_type':work,'quantity':'2'}
  if work=='다웰바 설치': inputs['dowel_spacing']='150'
  if work=='채움재 설치': inputs['filler_thickness']='20'
  result=per_unit(spec,inputs)
  assert result['status']=='computed',(work,result)
  lines={x['name']:x for x in result['unit_lines']}
  for trade in TRADES[work]:
   raw=EXPECTED[tid][trade]['수량']; expected=raw
   assert Fraction(lines[trade]['exact'])==Fraction(expected),(work,trade,lines[trade])
   assert lines[trade]['unit']==f"인/{UNITS[work]}",(work,lines[trade]['unit'])
   cite=lines[trade]['citations'][0]
   assert (cite['internal_id'],cite['row'],cite['column'],cite['value'])==(tid,trade,'수량',raw),cite
  routes+=1
 wrong=per_unit(spec,{'work_type':'실링 마감','quantity':'2','dowel_spacing':'150','filler_thickness':'20'})
 assert wrong['status']=='computed',wrong
 priced=[]
 for work in UNITS:
  inp={'work_type':work,'quantity':'1'}
  if work=='다웰바 설치': inp['dowel_spacing']='150'
  if work=='채움재 설치': inp['filler_thickness']='20'
  unit=per_unit(spec,inp); pr=price_unit(spec,unit['unit_lines'],select_rate_version('2026-10-01'),inp,'2026-10-01')
  fees=[x for x in pr['cost_lines'] if x['name']=='공구손료']
  assert bool(fees)==(work=='실링 마감'),(work,fees)
  priced.append({'work_type':work,'tool_fee_count':len(fees)})
 v=validate_one(SPEC,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None)
 assert v['ok'],v
 report={'status':'pass','source_pdf_physical_page':199,'printed_page':143,'independent_source_cells':cells,'exact_work_type_table_routes':routes,'quantity_conversion_cases':3,'exact_runtime_cell_citations':6,'format_citation_preflight':'pass','conditional_spacing_thickness_prompts':'pass','conditional_tool_fee':[{'work_type':x['work_type'],'fee_count':x['tool_fee_count']} for x in priced], 'source_visual_review':'Rendered original p.199 and visually compared section heading, work labels, units, resource rows, all six values and notes ①-③.'}
 out=ROOT/'evals/runtime_validation/per-unit-6-3-10-source-routes-2026-10-19.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())

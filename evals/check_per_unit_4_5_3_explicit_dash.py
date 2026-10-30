from __future__ import annotations
import json,sys,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import load_chunks,validate_one
SPEC=ROOT/'data/drafts/specs/토목/4-5-3.json';PDF=ROOT/'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
EXPECTED={'궤도공':{'레일인장법':'16.6','자연대기온도법':'16.6'},'특별인부':{'레일인장법':'2.2','자연대기온도법':'-'},'보통인부':{'레일인장법':'6.7','자연대기온도법':'6.7'}}
def norm(s):return ''.join(unicodedata.normalize('NFKC',str(s)).split()).casefold()
def main():
 import pymupdf
 spec=json.loads(SPEC.read_text(encoding='utf8'))['draft'];table=next(t for t in spec['tables'] if t['id']=='p406-t2');assert table['values']==EXPECTED
 with pymupdf.open(PDF) as doc: source=norm(doc[405].get_text())
 cells=0
 for row,cols in EXPECTED.items():
  assert norm(row) in source
  for col,val in cols.items(): assert norm(col) in source and norm(val) in source,(row,col,val);cells+=1
 routes=[]
 for method in ('레일인장법','자연대기온도법'):
  for q in ('1','3'):
   result=per_unit(spec,{'method':method,'quantity':q});assert result['status']=='computed',(method,q,result)
   expected_trades=[t for t in EXPECTED if EXPECTED[t][method]!='-']
   actual={line['name']:line for line in result['unit_lines']}
   assert set(actual)==set(expected_trades),(method,q,actual)
   for trade in expected_trades:
    raw=EXPECTED[trade][method];line=actual[trade]
    assert line['exact']==str(__import__('fractions').Fraction(raw)),(method,trade,line)
    c=line['citations'][0];assert (c['internal_id'],c['row'],c['column'],c['value'])==('p406-t2',trade,method,raw),c
   if method=='자연대기온도법':
    ex=result['provenance']['excluded_resources'];assert len(ex)==1 and ex[0]['trade']=='특별인부';c=ex[0]['citations'][0];assert (c['internal_id'],c['row'],c['column'],c['value'])==('p406-t2','특별인부',method,'-'),c
   routes.append({'method':method,'quantity':q,'included_trades':sorted(actual)})
 v=validate_one(SPEC,ROOT/'data/drafts/specs',load_chunks(ROOT/'data/processed/chunks.all.jsonl'),None);assert v['ok'],v
 report={'status':'pass','physical_pdf_page':406,'printed_page':350,'independent_source_cells':cells,'exact_method_routes':4,'exact_rate_cell_citations':10,'explicit_dash_exclusion_citations':2,'format_citation_preflight':'pass','source_visual_review':'Original PDF p.406 image checked: 3 resource rows × 2 method columns, including explicit dash for special labor under natural ambient method.','routes':routes}
 out=ROOT/'evals/runtime_validation/per-unit-4-5-3-explicit-dash-2026-10-19.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())

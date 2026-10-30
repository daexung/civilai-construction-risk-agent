"""Source and exact-path checks for valve tables with explicit dash cells."""
import json,sys
from fractions import Fraction
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
def main():
 doc=fitz.open(PDF); source={};
 r731=doc[730].find_tables().tables[0].extract(); left=r731[2];right=left
 sizes=left[0].splitlines()+left[3].splitlines(); plumbers=left[1].splitlines()+left[4].splitlines(); helpers=left[2].splitlines()+left[5].splitlines(); source['5-1-1']={s:{'배관공(인)':a,'보통인부(인)':b} for s,a,b in zip(sizes,plumbers,helpers)}
 r764=doc[763].find_tables().tables[1].extract(); sizes=r764[1][1].splitlines(); plumbers=r764[1][2].splitlines(); helpers=r764[1][3].splitlines(); source['10-2-3']={s:{'배 관 공(인)':a,'보통인부(인)':b} for s,a,b in zip(sizes,plumbers,helpers)}
 cases=[('기계설비','5-1-1','p731-t0','valve_size'),('기계설비','10-2-3','p764-t1','size')]; cells=routes=dashes=0
 for div,sec,tid,field in cases:
  path=ROOT/'data/drafts/specs'/div/(sec+'.json');pkg=json.loads(path.read_text(encoding='utf8'));spec=pkg['draft'];table=next(t for t in spec['tables'] if t['id']==tid);expected=source[sec];assert table['values']==expected,(sec,table['values'],expected);cells+=sum(len(v) for v in expected.values())
  chunks=load_chunks(ROOT/'data/processed/chunks.all.jsonl');v=validate_one(path,ROOT/'data/drafts',chunks,file_sha256(ROOT/'data/processed/chunks.all.jsonl'));assert not v['format_issues'] and not v['citation_issues'],(sec,v)
  for row,values in expected.items():
   result=per_unit(spec,{field:row,'quantity':'1'});assert result['status']=='computed',(sec,row,result)
   actual={x['name']:x['exact'] for x in result['unit_lines']}; want={name:str(Fraction(value)) for name,value in values.items() if value!='-'};assert actual==want,(sec,row,actual,want)
   assert len(result['provenance']['excluded_resources'])==sum(value=='-' for value in values.values());dashes+=len(result['provenance']['excluded_resources']);routes+=1
 print(json.dumps({'status':'pass','sections':['기계설비/5-1-1','기계설비/10-2-3'],'pdf_cells_compared':cells,'exact_routes':routes,'dash_cells_preserved_as_exclusions':dashes,'citation_preflight':'pass','visual_pages_printed':[675,708],'full_rule_verification':False},ensure_ascii=False))
if __name__=='__main__':main()

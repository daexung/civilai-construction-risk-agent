"""Compare 6-3-4 source grid and exact note multipliers offline."""
import json,sys
from fractions import Fraction
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SPEC=ROOT/"data/drafts/specs/토목/6-3-4.json";PDF=ROOT/"data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
def main():
 d=json.loads(SPEC.read_text(encoding="utf8"))["draft"]; doc=fitz.open(PDF); tabs=doc[424].find_tables().tables; tab=next(t for t in tabs if len(t.extract()[0])==6); rows=tab.extract(); left_sizes=rows[2][0].splitlines(); left_a=rows[2][1].splitlines(); left_b=rows[2][2].splitlines(); right_sizes=rows[2][3].splitlines(); right_a=rows[2][4].splitlines(); right_b=rows[2][5].splitlines(); source={**{s:{"A종":a,"B종":b} for s,a,b in zip(left_sizes,left_a,left_b)},**{s:{"A종":a,"B종":b} for s,a,b in zip(right_sizes,right_a,right_b)}}
 table=next(t for t in d["tables"] if t["id"]=="p425-t0"); assert table["values"]==source,(table["values"],source); assert len(source)==25 and sum(v=="-" for r in source.values() for v in r.values())==12
 chunks=load_chunks(ROOT/"data/processed/chunks.all.jsonl"); v=validate_one(SPEC,ROOT/"data/drafts",chunks,file_sha256(ROOT/"data/processed/chunks.all.jsonl")); assert not v["format_issues"] and not v["citation_issues"],v
 checked=blocked=0
 for size,row in source.items():
  for typ in ("A종","B종"):
   for work,factor in (("전체 작업",Fraction(1)),("금긋기 및 절단",Fraction(7,10)),("선단가공(Beveling)",Fraction(3,10))):
    result=per_unit(d,{"pipe_diameter":size,"pipe_type":typ,"work_type":work,"quantity":"1"}); checked+=1
    if typ=="B종" and int(size.replace(",",""))<=600:
     assert result["status"]=="blocked",(size,typ,work,result); blocked+=1; continue
    expected=Fraction(row[typ])*factor; actual=result.get("unit_lines",[{}])[0].get("exact")
    assert result["status"]=="computed" and actual==str(expected),(size,typ,work,result.get("status"),actual,str(expected))
 print(json.dumps({"status":"pass","printed_page":369,"pdf_grid_cells":50,"dash_cells":12,"computed_or_blocked_routes":checked,"explicit_source_dash_blocks":blocked,"70_30_base_multipliers":"3×38 applicable cell combinations checked","citation_preflight":"pass","full_rule_verification":False},ensure_ascii=False))
if __name__=="__main__":main()

"""Independent source-cell and exact-output checks for common 7-4-1."""
import json, sys
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SPEC=ROOT/"data/drafts/specs/공통/7-4-1.json"
EXPECTED={"석공":{"수량":"3"},"줄눈공":{"수량":"1"},"보통인부":{"수량":"2"},"바닥부":{"테라조판":"15","화강석":"12"},"계단부":{"테라조판":"13","화강석":"11"}}
EXPECTED_PER_M2={("바닥부","테라조판"): ["1/5","1/15","2/15"],("바닥부","화강석"): ["1/4","1/12","1/6"],("계단부","테라조판"): ["3/13","1/13","2/13"],("계단부","화강석"): ["3/11","1/11","2/11"]}
def main():
 pkg=json.loads(SPEC.read_text(encoding="utf8")); s=pkg["draft"]; t=next(t for t in s["tables"] if t["id"]=="p217-t2")
 assert t["values"]==EXPECTED
 chunks=load_chunks(ROOT/"data/processed/chunks.all.jsonl"); text=chunks["p217-t2"]["text"]
 for row,cells in EXPECTED.items():
  for col,val in cells.items():
   if row in ("석공","줄눈공","보통인부"): assert f"{row} | 단위 인 | 수량 {val}" in text
   else: assert f"시공부위 {row}" in text and f"{col} {val}" in text
 v=validate_one(SPEC,ROOT/"data/drafts",chunks,file_sha256(ROOT/"data/processed/chunks.all.jsonl")); assert not v["format_issues"] and not v["citation_issues"],v
 for (part,stone),expected in EXPECTED_PER_M2.items():
  r=adjusted_daily_crew(s,{"volume":"1","part":part,"stone_type":stone})
  assert r["status"]=="computed",(part,stone,r.get("reason"))
  actual=[x["exact"] for x in r["unit_lines"]]
  assert actual==expected,(part,stone,actual,expected)
  for line in r["unit_lines"]:
   cite=line["citations"][0]; assert (cite["row"],cite["column"],cite["value"]) in [("석공","수량","3"),("줄눈공","수량","1"),("보통인부","수량","2")]
 print(json.dumps({"status":"pass","section":"공통/7-4-1","source_cells":10,"source_axis_interpretation":"labor crew independent of part/stone; productivity by part x stone","exact_paths":4,"rule_scope":"source table cells and daily-crew division; full referenced rounding-note audit not claimed"},ensure_ascii=False))
if __name__=="__main__": main()

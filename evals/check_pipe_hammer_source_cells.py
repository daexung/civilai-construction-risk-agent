"""PDF-transcribed cells and exact calculator checks for 5-4-1."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one
SPEC=ROOT/"data/drafts/specs/기계설비/5-4-1.json"
EXPECTED={"ø15 ∼ 25":{"배관공(인)":"0.028","보통인부(인)":"-"},"32 ∼ 50":{"배관공(인)":"0.056","보통인부(인)":"-"},"65":{"배관공(인)":"0.073","보통인부(인)":"0.024"},"80":{"배관공(인)":"0.100","보통인부(인)":"0.033"},"100":{"배관공(인)":"0.136","보통인부(인)":"0.045"},"125":{"배관공(인)":"0.181","보통인부(인)":"0.060"},"150":{"배관공(인)":"0.226","보통인부(인)":"0.075"},"200":{"배관공(인)":"0.316","보통인부(인)":"0.105"}}
EXPECTED_OUTPUT={"ø15 ∼ 25":["7/250"],"32 ∼ 50":["7/125"],"65":["73/1000","3/125"],"80":["1/10","33/1000"],"100":["17/125","9/200"],"125":["181/1000","3/50"],"150":["113/500","3/40"],"200":["79/250","21/200"]}
def main():
 pkg=json.loads(SPEC.read_text(encoding="utf8")); spec=pkg["draft"]; table=next(t for t in spec["tables"] if t["id"]=="p733-t0"); assert table["values"]==EXPECTED
 chunks=load_chunks(ROOT/"data/processed/chunks.all.jsonl"); text=chunks["p733-t0"]["text"]
 for row,cells in EXPECTED.items(): assert f"{row} | {cells['배관공(인)']} | {cells['보통인부(인)']}" in text
 v=validate_one(SPEC,ROOT/"data/drafts",chunks,file_sha256(ROOT/"data/processed/chunks.all.jsonl")); assert not v["format_issues"] and not v["citation_issues"],v
 for size,expected in EXPECTED_OUTPUT.items():
  r=per_unit(spec,{"size":size,"quantity":"1","wall_grooving":False}); actual=[x["exact"] for x in r.get("unit_lines",[])]; assert r["status"]=="computed" and actual==expected,(size,r,expected)
 print(json.dumps({"status":"pass","section":"기계설비/5-4-1","printed_page":677,"source_cells":16,"rows":8,"dash_cells":"2, preserved as source exclusions (not zero rates)","exact_rate_paths":8,"full_rule_verification":False},ensure_ascii=False))
if __name__=="__main__": main()

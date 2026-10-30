"""Use the single exact source total row and resource-keyed columns."""
from __future__ import annotations
import json, sys
from fractions import Fraction
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa:E402
from pipeline.validate_drafts import file_sha256,load_chunks,validate_one  # noqa:E402

SPEC=ROOT/"data/drafts/specs/토목/9-18-5.json"
CHUNKS=ROOT/"data/processed/chunks.all.jsonl"
AUDIT=ROOT/"evals/runtime_validation/per-unit-9-18-5-total-row-2026-10-19.json"
TABLE="p621-t0"
EXPECTED={"지적기사":"0.004","지적산업기사":"0.043"}

def main()->int:
 package=json.loads(SPEC.read_text(encoding="utf8"));spec=package["draft"]
 rate=spec["quantity_model"]["params"]["unit_rate_table"]
 table=next(t for t in spec["tables"] if t["id"]==TABLE)
 assert table["values"]=={"합계":EXPECTED}
 assert rate["row_input"]=="합계" and rate["trades"]==list(EXPECTED)
 rate["column_input"]=None
 SPEC.write_text(json.dumps(package,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 routes=outputs=0
 for quantity in ["1","10"]:
  result=per_unit(spec,{"quantity":quantity});assert result["status"]=="computed",result
  got={line["name"]:Fraction(line["exact"]) for line in result["unit_lines"]}
  assert got=={name:Fraction(value) for name,value in EXPECTED.items()},(quantity,got)
  for line in result["unit_lines"]:
   cite=next(c for c in line["citations"] if c.get("internal_id")==TABLE)
   assert (cite.get("row"),cite.get("column"),cite.get("value"))==("합계",line["name"],EXPECTED[line["name"]])
   assert Fraction(line["exact"])*Fraction(quantity)==Fraction(EXPECTED[line["name"]])*Fraction(quantity)
  routes+=1;outputs+=len(got)
 validation=validate_one(SPEC,ROOT/"data/drafts",load_chunks(CHUNKS),file_sha256(CHUNKS))
 assert not validation["format_issues"],validation["format_issues"]
 assert not validation["citation_issues"],validation["citation_issues"]
 record={"status":"pass","section":"토목/9-18-5","table_id":TABLE,
  "source":"Original PDF p.621 / printed p.565; final totals in two trade columns visually checked",
  "independent_source_cells":2,"exact_quantity_routes":routes,
  "exact_rate_outputs_with_citations":outputs,"quantities_tested":["1","10"],
  "format_preflight":"pass","citation_preflight":"pass","full_rule_verification":False,
  "not_calculated":"source says machine/equipment and small materials are accounted separately"}
 AUDIT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print(json.dumps(record,ensure_ascii=False,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())

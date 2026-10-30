"""Source-derived labor/material range checks for the routed daily tables."""
from __future__ import annotations
import json,re
from fractions import Fraction
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
path=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json")
          if any(t.get("id")=="p653-t0" for t in json.loads(p.read_text(encoding="utf-8"))["draft"].get("tables",[])))
pkg=json.loads(path.read_text(encoding="utf-8"));spec=pkg["draft"];materials=spec["inputs"][0]["allowed_values"]
text=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[652].extract_text() or ""
compact=re.sub(r"\s+","",text)
assert all(token in compact for token in ("25","200","165","75","120","2%","1.04","0.022","0.035"))
expected=[("25","3","1"),("200","2","1"),("165","2","1")]
for material,(rate,trade_count,helper_count) in zip(materials,expected):
 out=adjusted_daily_crew(spec,{"material":material,"length":"1000","height":"100"})
 assert out["status"]=="computed",(material,out)
 assert out["daily_volume_m3"]==rate
 crew=spec["quantity_model"]["params"]["crew"]["trades_by_input"][material]
 assert Fraction(out["person_days"][crew[0]])==Fraction(1000*int(trade_count),int(rate))
 assert Fraction(out["person_days"][crew[1]])==Fraction(1000*int(helper_count),int(rate))
 assert out["provenance"]["daily_volume_m3"]["base_output"]["table"] in ("p653-t0","p653-t1")
 ranges=[x for x in out["unit_lines"] if x["kind"]=="material_range"]
 if rate=="25":
  assert next(x for x in out["unit_lines"] if x["kind"]=="material")["exact"]=="1000"
  assert not ranges
 else:
  assert len(ranges)==1 and (ranges[0]["minimum"],ranges[0]["maximum"],ranges[0]["unit"])==("22","35","kg")
 assert all(x.get("citations") for x in out["unit_lines"])
for bad in ("74","121"):
 out=adjusted_daily_crew(spec,{"material":materials[0],"length":"1000","height":bad})
 assert out["status"]=="blocked",(bad,out)
assert spec["not_calculated"] and spec["not_calculated"][0]["cite"]["table_id"]=="p653-t2"
print("PASS source p.597: three material routes use 25/200/165 m/day and matching source crews.")
print("PASS p653-t2: deterministic board materials and the source adhesive interval 22-35 kg/1000m preserved.")
print("PASS 75-120mm applicability; heights 74mm and 121mm are blocked.")

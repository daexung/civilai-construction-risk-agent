"""Promote 13-2-5 only after its source matrix audit passes."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
index=ROOT/"data/drafts/executable.json"
package=json.loads((ROOT/"data/drafts/specs/기계설비/13-2-5.json").read_text(encoding="utf8"))
data=json.loads(index.read_text(encoding="utf8"))
ident=package["draft"]["id"]
assert package["calc_type"]=="per_unit" and package["draft"]["quantity_model"]["name"]=="per_unit"
assert len(json.loads((ROOT/"evals/runtime_validation/mechanical-13-2-5-preheat-source-audit-2026-10-19.json").read_text(encoding="utf8"))["scope"])>=5
if ident in data["executable"]:
 print("already executable",ident)
else:
 item=next((x for x in data["skipped"] if x["id"]==ident),None)
 assert item and item.get("stage")=="calculator_selection",item
 data["skipped"].remove(item);data["executable"].append(ident)
 index.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print("promoted",ident)

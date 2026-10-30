"""Source-derived execution checks for the table-driven two-basis activity."""
from __future__ import annotations
import json,re
from pathlib import Path
from pypdf import PdfReader
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
ROOT=Path(__file__).resolve().parents[1]
path=next(p for p in (ROOT/"data/drafts/specs").rglob("*.json")
          if any(t.get("id")=="p652-t1" for t in json.loads(p.read_text(encoding="utf-8"))["draft"].get("tables",[])))
pkg=json.loads(path.read_text(encoding="utf-8"));spec=pkg["draft"];params=spec["quantity_model"]["params"]
text=PdfReader(next((ROOT/"data/raw/standard_estimation").glob("*.pdf"))).pages[651].extract_text() or ""
compact=re.sub(r"\s+","",text)
assert all(token in compact for token in ("20","80","37","50","100","2%"))
values=spec["tables"][0]["values"];types=spec["inputs"][1]["allowed_values"]
def row_for(panel,required_column):
 return next(k for k,v in values.items() if k.startswith(panel+" ") and required_column in v)
output_col=params["base_output"]["column"];count_col=params["crew"]["column"]
trades=params["crew"]["trades"];crane=params["equipment"][0]["name"]
joint=params["additional_work"][0]["base_output"]["row"]
base={"panel_thickness":"75","panel_type":types[1],"area":"160","joint_required":True,"joint_length":"37"}
out=adjusted_daily_crew(spec,base)
assert out["status"]=="computed",out
assert out["work_days"]=="2",out
assert out["person_days"][trades[0]]=="7",out["person_days"]
assert out["person_days"][trades[1]]=="2",out["person_days"]
assert out["equipment_days"][crane]=="2",out["equipment_days"]
assert any(line.get("task_source") and line["name"]==trades[0] for line in out["unit_lines"])
assert all(line.get("citations") for line in out["unit_lines"] if line["kind"]=="labor")
no_joint=adjusted_daily_crew(spec,{**base,"joint_required":False,"joint_length":None})
assert no_joint["status"]=="computed",no_joint
assert no_joint["person_days"][trades[0]]=="6"
wall=adjusted_daily_crew(spec,{**base,"panel_type":types[0],"joint_required":False,"joint_length":None})
assert wall["status"]=="computed" and crane not in wall["equipment_days"],wall
outside=adjusted_daily_crew(spec,{**base,"panel_thickness":"49"})
assert outside["status"]=="blocked",outside
print("PASS source p.596: rates 20/80, joint rate 37, tool cost 2%, and thickness scope checked.")
print("PASS roof area 160 plus joint length 37: source-derived labor days 7 and 2, equipment-days 2.")
print("PASS inactive joint and partition applicability; out-of-scope thickness is blocked.")

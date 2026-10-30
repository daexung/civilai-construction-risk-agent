"""Connect the two continuation labor rows to their exact source columns."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/토목/8-1-3.json"
spec = json.loads(PATH.read_text(encoding="utf-8"))
draft = spec["draft"]
params = draft["quantity_model"]["params"]
selector = {"input": "rock_type", "exact_component_inputs": ["rock_type"], "input_contains": ["hole_size"]}
params["unit_rate_table"]["column_input"] = selector
for material in params["additional_materials"]:
    material["column_selector"] = selector
params["additional_unit_rates"] = [{
    "table": "p454-t0",
    "basis": "m",
    "quantity_input": "quantity",
    "trades": ["특별인부", "보통인부"],
    "row_by_trade": {"특별인부": "특별인부", "보통인부": "보통인부"},
    "column_selector": selector,
    "source": "PDF printed p.398, continuation labor rows in the exact rock/hole columns",
}]
steps = draft["quantity_model"]["steps"]
steps.insert(1, "p454-t0 표에서 특별인부와 보통인부를 각각 정확한 암종·BX/NX 열로 조회한다.")
PATH.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("connected p454-t0 continuation labor rows with exact rock/hole axes")

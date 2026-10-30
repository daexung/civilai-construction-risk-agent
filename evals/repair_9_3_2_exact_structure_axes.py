"""Route the two exact continuation tables and both structure subcolumns."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = next(p for p in (ROOT / "data/drafts/specs").rglob("*.json")
            if (lambda d: d.get("division") == "기계설비" and d.get("section_no") == "9-3-2")
            (json.loads(p.read_text(encoding="utf8"))["draft"]))
package = json.loads(path.read_text(encoding="utf-8"))
draft = package["draft"]
rate = draft["quantity_model"]["params"]["unit_rate_table"]
rate["table_selector"] = {"input": "hole_diameter", "values": {
    **{f"{n}mm": "p759-t2" for n in (25, 50, 75, 100)},
    **{f"{n}mm": "p760-t0" for n in (150, 200, 250, 300, 350, 400)},
}}
rate["column_input"] = {"input": "concrete_thickness",
                         "contains": ["콘크리트 두께 {value}"],
                         "input_contains": ["structure_type"]}
draft["quantity_model"]["steps"][0] = "hole_diameter에 맞춰 p759-t2 또는 p760-t0 원문 표를 정확히 선택한다."
draft["quantity_model"]["steps"][1] = "콘크리트 두께와 구조 위치(바닥/벽체)에 맞는 단위당 인력 품을 찾는다."
path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("mapped 25-100mm to p759-t2, 150-400mm to p760-t0, and selected thickness plus floor/wall")

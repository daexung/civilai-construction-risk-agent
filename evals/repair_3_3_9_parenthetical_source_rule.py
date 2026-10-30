"""Use the exact source note to select ordinary vs diver cell values."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "data/drafts/specs/공통/3-3-9.json"
package = json.loads(path.read_text(encoding="utf-8"))
draft = package["draft"]
rate = draft["quantity_model"]["params"]["unit_rate_table"]
rate["parenthetical_value_selector"] = {
    "input": "drilling_method",
    "values": {"일반 천공": "primary", "잠수부 천공": "parenthetical"},
    "source": "PDF printed p.74 [주] ①: values in parentheses are for diver drilling",
    "cite": {"chunk_id": "p130-x10", "quote": "( )내는 잠수부 천공시의 품이다."},
}
rate["trades"] = ["폭약", "뇌관", "비트", "화약취급공", "착암공", "보통인부", "잠수부", "소형브레이커", "공기압축기"]
rate["resource_units"] = {"폭약": "kg", "뇌관": "개", "비트": "개",
                          "화약취급공": "인", "착암공": "인", "보통인부": "인",
                          "잠수부": "조", "소형브레이커": "hr", "공기압축기": "hr"}
rate["resource_kinds"] = {"폭약": "material", "뇌관": "material", "비트": "material",
                           "화약취급공": "labor", "착암공": "labor", "보통인부": "labor",
                           "잠수부": "labor", "소형브레이커": "equipment", "공기압축기": "equipment"}
rate["preserve_labor_source_unit"] = ["잠수부"]
draft["quantity_model"]["steps"].insert(0, "표에서 blast_type 열의 값을 선택하고, 착암공·잠수부의 괄호 수치는 drilling_method에 따라 일반 또는 잠수부 천공 값으로 읽는다.")
path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("connected p130 parenthetical cells to the source-defined drilling method")

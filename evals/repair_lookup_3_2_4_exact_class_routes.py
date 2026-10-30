"""Route tunnel classes to the two exact source equipment tables."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/3-2-4.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/3-2-4-spec-before-exact-class-routes.json").exists():
        (ROOT / "tmp/3-2-4-spec-before-exact-class-routes.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    tunnel_class = next(item for item in spec["inputs"] if item["name"] == "tunnel_class")
    tunnel_class.pop("source_table_map", None)
    selector = {
        "name": "lookup_type", "type": "enum",
        "allowed_values": ["A·B·C군 표준 장비조합", "소형터널 장비조합"],
        "unit": None, "required": True,
        "ask": "조회할 원문 장비조합 표를 선택해주세요.",
        "source": "PDF 341쪽 A·B·C군 표 / 소형터널 표",
        "source_table_map": {"A·B·C군 표준 장비조합": "p397-t0", "소형터널 장비조합": "p397-t2"},
    }
    role = {
        "name": "equipment_role", "type": "enum",
        "allowed_values": ["발파천공및 록볼트 천공장비", "버력상차장비", "버력운반장비",
                           "발파천공천공장비"],
        "unit": None, "required": True,
        "ask": "조회할 장비 역할은 무엇입니까?",
        "source": "PDF 341쪽 선택한 장비조합 표의 행 구분",
        "source_row_key": True,
    }
    inputs = [item for item in spec["inputs"] if item["name"] not in {"lookup_type", "equipment_role"}]
    class_index = next(i for i, item in enumerate(inputs) if item["name"] == "tunnel_class")
    inputs[class_index:class_index] = [selector, role]
    spec["inputs"] = inputs
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("routed A/B/C to p397-t0 and small tunnel to p397-t2; custom combination remains source-blocked")


if __name__ == "__main__":
    main()

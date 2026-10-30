"""Map open distance intervals to exact source cells; block ambiguous endpoints."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/3-1-1.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/3-1-1-spec-before-numeric-source-ranges.json").exists():
        (ROOT / "tmp/3-1-1-spec-before-numeric-source-ranges.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    distance = next(field for field in spec["inputs"] if field["name"] == "distance")
    table = next(table for table in spec["tables"] if table["id"] == "p393-t1")
    columns = list(table["values"]["할증률(%)"])
    ranges = []
    for index, column in enumerate(columns):
        lower = index * 500
        upper = (index + 1) * 500 if index < len(columns) - 1 else None
        ranges.append({"table_id": "p393-t1", "row": "할증률(%)", "column": column,
                       "min": lower if index else 0,
                       "min_inclusive": index == 0,
                       "max": upper,
                       "max_inclusive": False})
    distance["source_range_map"] = ranges
    boundaries = list(range(500, 5001, 500))
    reason = "원문 구간의 공통 경계(500m 단위)는 양쪽 구간에 걸릴 수 있어 자동 선택하지 않음"
    spec.setdefault("blocked", [])
    spec["blocked"] = [item for item in spec["blocked"]
                       if item.get("source") != "PDF 337쪽 ④ 거리 구간 경계"]
    for boundary in boundaries:
        spec["blocked"].append({
            "condition": f"갱구에서 뚫기점까지 거리가 정확히 {boundary}m인 경우",
            "blocked_if": {"input": "distance", "op": "==", "value": boundary},
            "reason": reason, "source": "PDF 337쪽 ④ 거리 구간 경계",
            "cite": {"table_id": "p393-t1"},
        })
    spec.setdefault("open_questions", [])
    question = "PDF 337쪽 p393-t1의 500m 단위 공통 끝점(500~5,000m)을 어느 인접 구간에 귀속할지 원문 표기가 겹침; 경계는 차단하고 비경계 거리만 자동 선택"
    if question not in spec["open_questions"]:
        spec["open_questions"].append(question)
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("installed 11 exact source ranges and six endpoint blocks; endpoints remain unresolved")


if __name__ == "__main__":
    main()

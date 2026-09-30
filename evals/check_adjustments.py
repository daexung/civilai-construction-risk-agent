"""원문으로 확인한 품 할증·감과 보류 경계를 검사한다."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools.calc import adjustments  # noqa: E402
from agent.tools.calc.per_unit import per_unit  # noqa: E402


def main() -> int:
    spec = json.loads((ROOT / "data/drafts/specs/공통/6-1-5.json").read_text(encoding="utf-8"))["draft"]
    inputs = {"area": "100", "type": "신구-콘크리트 접착제바르기",
              "ceiling_applied": False, "scaffold_used": False, "floor_level": "지하층 및 1∼3층",
              "floor_level_19_plus": 19, "thickness_adjusted": False, "thickness": "1"}
    checks = []
    inputs["ceiling_applied"] = True
    result = per_unit(spec, inputs)
    checks.append(("20% 원문 확인 후 가산", result["status"] == "computed"
                   and result["unit_lines"][0]["applied"] == "0.144"
                   and result["unit_lines"][0]["adjustments"][0]["citations"][0]["internal_id"] == "p188-t0"))
    inputs["scaffold_used"] = True
    blocked = per_unit(spec, inputs)
    checks.append(("비계 선택 적용 보류", blocked["status"] == "blocked"
                   and any(citation["internal_id"] == "p188-x6"
                           for citation in blocked["citations"])))
    mechanical = json.loads((ROOT / "data/drafts/specs/공통/6-2-5.json").read_text(encoding="utf-8"))["draft"]
    source = adjustments._evidence(mechanical, mechanical["quantity_model"]["params"]["surcharges"][0])
    checks.append(("6-2-5 요율 표와 적용 문장", source is not None
                   and source["rate"] == adjustments.parse_fraction("0.1")
                   and [citation["internal_id"] for citation in source["citations"]]
                   == ["p191-t1", "p191-t0"]
                   and "높이에 따라 인력품에 다음 요율을 적용한다" in source["quote"]))
    g1 = per_unit(mechanical, {"quantity": "1", "rebar_diameter": 35,
                               "work_height": "10m~20m 미만"})
    g1_lines = {line["name"]: line for line in g1.get("unit_lines", [])}
    checks.append(("G1 6-2-5 할증 품", g1["status"] == "computed"
                   and g1_lines["용접공"]["applied"] == "0.066"
                   and g1_lines["연마공"]["applied"] == "0.165"
                   and g1_lines["조력공"]["applied"] == "0.121"
                   and g1_lines["절단공"]["applied"] == "0.099"))

    base = copy.deepcopy(spec)
    base["quantity_model"]["params"]["surcharges"] = []
    base["quantity_model"]["params"]["note_adjustments"] = []
    line = {"kind": "labor", "name": "도장공", "exact": "1", "applied": "1", "places": 0,
            "formula": "1", "citations": []}
    original = adjustments._evidence
    chunk = {"chunk_id": "p188-t0"}
    try:
        adjustments._evidence = lambda _spec, item, _inputs=None: {
            "chunk": chunk, "quote": item["source"],
            "rate": (adjustments._number(item["source"]) or ("", 0))[1],
            "citations": adjustments.resolve_cites({"chunk_id": "p188-t0", "quote": item["source"]})}
        def run(*items):
            candidate = copy.deepcopy(base)
            candidate["quantity_model"]["params"]["surcharges"] = list(items)
            sample = copy.deepcopy(line)
            return adjustments.apply_adjustments(candidate, {}, [sample]), sample

        a, sample = run({"source": "10% 가산", "rate": "0.1"},
                        {"source": "20% 가산", "rate": "0.2"})
        checks.append(("할증 합산 1.3", a["status"] == "computed" and sample["applied"] == "1.3"))
        a, sample = run({"source": "10% 감하여", "rate": "0.1"},
                        {"source": "×0.8", "rate": "0.8"})
        checks.append(("감·승수 기본품 선적용", a["status"] == "computed" and sample["applied"] == "0.72"))
        for phrase in ("까지", "할 수 있으며", "이내", "범위", "내외"):
            a, _ = run({"source": f"20% 가산 {phrase}", "rate": "0.2"})
            checks.append((f"선택 문구 {phrase} 보류", a["status"] == "blocked"))
        a, _ = run({"source": "품을 가산한다", "rate": "0.2"})
        checks.append(("원문 수치 없음 보류", a["status"] == "blocked"))
        a, _ = run({"source": "표 참조 20% 가산", "rate": "0.2"})
        checks.append(("표 참조 보류", a["status"] == "blocked"))
        a, _ = run({"source": "누적 20% 가산", "rate": "0.2"})
        checks.append(("누적 규칙 보류", a["status"] == "blocked"))
        a, sample = run({"source": "현장 여건을 검토한다"})
        checks.append(("설명 메모", a["status"] == "computed" and len(a["memos"]) == 1
                       and sample["applied"] == "1"))
    finally:
        adjustments._evidence = original
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

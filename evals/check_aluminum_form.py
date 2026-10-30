"""Source-driven checks for aluminum-form layer execution and applicability gates."""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402


def main() -> int:
    path = next(path for path in (ROOT / "data/drafts/specs").rglob("*.json")
                if json.loads(path.read_text(encoding="utf-8"))["draft"].get("section_no") == "6-3-7"
                and any(field["name"] == "is_rc_wall_structure"
                        for field in json.loads(path.read_text(encoding="utf-8"))["draft"]["inputs"]))
    spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
    pdf_page = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[196].extract_text() or ""
    compact = re.sub(r"\s+", "", pdf_page)
    for token in ("6-3-7", "형틀목공인430", "보통인부인1", "40", "70", "단면의형태및크기"):
        assert token in compact, token
    fields = {field["name"]: field for field in spec["inputs"]}
    valid = {"layer_type": fields["layer_type"]["allowed_values"][-1], "area": "70",
             "section_change": False, "is_rc_wall_structure": True}
    result = adjusted_daily_crew(spec, valid, labor_only=True)
    assert result["status"] == "computed", result
    assert result["daily_volume_m3"] == "70" and result["work_days"] == "1"
    assert result["person_days"] == {"형틀목공": "4", "보통인부": "1"}
    citations = [cite for line in result["unit_lines"] for cite in line.get("citations", [])]
    base_cite = result["provenance"]["daily_volume_m3"]["base_output"]
    assert base_cite.get("table") == "p197-t1" and base_cite.get("value") == "70"
    assert len(result["not_calculated"]) == 1

    out_of_scope = adjusted_daily_crew(spec, {**valid, "is_rc_wall_structure": False}, labor_only=True)
    assert out_of_scope["status"] == "blocked", out_of_scope
    adjustment_required = adjusted_daily_crew(spec, {**valid, "section_change": True}, labor_only=True)
    assert adjustment_required["status"] == "blocked", adjustment_required
    print("PASS 원문 p.141 표·범위·별도계상 대조; 층별 시공량·노무 계산 및 두 적용조건 차단")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

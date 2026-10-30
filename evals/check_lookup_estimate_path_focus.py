"""Focused consultation and price flow for the source-repaired lookup and enum overlap."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from backend.agent.estimate import tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402
from backend.api.main import _computed_result_out  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402


def check(key: tuple[str, str], answers: dict) -> dict:
    spec = next(s for s in load_specs().values() if (s["division"], s["section_no"]) == key)
    hit = {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
           "section": f"{spec['section_no']} {spec['title']}", "page": 255, "table_id": "p311-t0",
           "text": spec["title"], "chunk_id": "focused-source-hit"}
    session = tools.new_estimate(spec["title"])
    assert tools.find_work(session, hits=[hit])["status"] == "ok", spec["id"]
    with patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})):
        applied = tools.set_conditions(session, spec["title"], source="answer",
                                       values={name: {"value": value, "evidence": str(value)}
                                               for name, value in answers.items()})
        assert not applied.get("rejected"), (spec["id"], applied)
        computed = tools.compute_labor(session)
        assert computed["status"] == "ok", (spec["id"], computed)
        item = session["items"][session["item_order"][0]]
        output = _computed_result_out(item["computed_result"], spec, "")
        assert output["lines"] and all(line["citations"] is not None for line in output["lines"])
        priced = tools.estimate_cost(session)
        assert priced["status"] == "ok", (spec["id"], priced)
        for line in item["computed_result"].get("unit_lines", []):
            price_unit(spec, [line], select_rate_version("2026-06-01"), answers)
        return {"id": spec["id"], "calc_status": item["computed_result"]["status"],
                "output_lines": len(output["lines"]), "price_status": priced["status"],
                "reference_only": bool(priced["data"].get("reference_only"))}


def main() -> int:
    rows = [check(("공통", "8-3-7"), {"machine_code": "6105-0190"}),
            check(("공통", "2104-0010"), {"machine_spec": "300ton"}),
            check(("공통", "2-2-4"), {"duration": "1개월", "support_type": "강관 동바리"})]
    print(json.dumps({"status": "pass", "cases": rows,
                      "duration_overlap": "per-spec enum retained instead of global numeric duration"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

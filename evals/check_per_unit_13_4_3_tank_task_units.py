"""Source and route audit for mechanical 13-4-3's four task-specific tables."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import sys
from fractions import Fraction
from pathlib import Path
from collections import Counter, defaultdict
from unittest.mock import patch

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402
from backend.agent.estimate import tools as estimate_tools  # noqa: E402
from backend.agent.nodes import select as select_node  # noqa: E402
from backend.agent.tools.source import citation as citation_runtime  # noqa: E402
from evals.check_draft_executability import _values  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/13-4-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGES = [ROOT / "evals/runtime_validation/source-p821-13-4-3-tank.png",
          ROOT / "evals/runtime_validation/source-p822-13-4-3-tank.png"]
OUT = ROOT / "evals/runtime_validation/per-unit-13-4-3-task-units-source-audit-2026-10-19.json"
PLATES = ["8t×5ft×20ft이하", "12×5×20〃", "16×5×20〃", "20×5×20〃", "24×5×20〃",
          "28×5×20〃", "32×5×20〃", "36×5×20〃", "40×5×20〃"]
CAPS = ["50\n이하", "100\n이하", "300\n이하", "500\n이하", "1,500\n이하",
        "3,000\n이하", "5,000\n이하", "10,000\n이하", "10,000\n이상"]
PLATE_RATES = [
    ("0.087", "0.328", "0.131"), ("0.177", "0.477", "0.191"), ("0.211", "0.790", "0.315"),
    ("0.252", "0.972", "0.378"), ("0.307", "1.184", "0.461"), ("0.361", "1.392", "0.542"),
    ("0.415", "1.602", "0.624"), ("0.470", "1.813", "0.706"), ("0.524", "2.023", "0.787")]
TANK_TRADES = ["건설기계운전공", "비계공", "특별인부", "(플랜트제관공)", "(플랜트용접공)", "인력운반공", "보통인부", "배관공"]
TANK_RATES = [
    ["1.922", "1.576", "1.476", "1.321", "1.093", "0.911", "0.856", "0.799", "0.702"],
    ["0.928", "0.759", "0.711", "0.637", "0.527", "0.439", "0.399", "0.378", "0.357"],
    ["8.475", "6.908", "6.469", "5.790", "4.792", "3.993", "2.499", "2.163", "2.163"],
    ["3.522", "2.889", "2.705", "2.422", "2.004", "1.670", "1.447", "1.040", "0.983"],
    ["3.081", "2.519", "2.359", "2.111", "1.747", "1.456", "1.456", "1.899", "2.041"],
    ["0.160", "0.131", "0.123", "0.110", "0.091", "0.076", "0.076", "0.076", "0.076"],
    ["4.950", "4.048", "3.791", "3.393", "2.808", "2.340", "2.010", "1.860", "1.720"],
    ["0.145", "0.119", "0.118", "0.100", "0.083", "0.069", "0.047", "0.029", "0.025"]]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    pkg = json.loads(SPEC.read_text(encoding="utf-8")); spec = pkg["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    assert [tables["p821-t2"]["values"][plate][trade] for plate in PLATES for trade in
            ("일반기계운전사\n(윈치운전)", "플랜트\n제관공", "특별인부")] == [v for row in PLATE_RATES for v in row]
    assert tables["p822-t0"]["values"]["작업구분"] == {"현도": "0.437", "괘서": "1.161", "절단": "0.318", "계": "1.916"}
    assert [tables["p822-t1"]["values"]["공량"][trade] for trade in
            ("비계공", "건설기계운전(조/대)", "특별인부")] == ["0.073", "0.037", "0.073"]
    assert [[tables["p822-t2"]["values"][trade][cap] for cap in CAPS] for trade in TANK_TRADES] == TANK_RATES

    doc = pymupdf.open(PDF)
    p765, p766 = doc[820].get_text("text"), doc[821].get_text("text")
    assert "13-4-3 STORAGE TANK" in p765 and "(매당)" in p765 and "0.524" in p765
    assert "766" in p766 and "(ton당)" in p766 and "0.437" in p766 and "0.073" in p766 and "40∼50%" in p766
    assert "용접공은 용접장의 증감에 따라 조정한다." in p766

    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ci = chunks_by_id_from_list(chunks)
    cell_count = 0
    for table_id, table in tables.items():
        if table_id == "p832-t1":
            continue
        for row, values in table["values"].items():
            for col, value in values.items():
                if table_id == "p822-t1" and row == "비고":
                    continue
                if not str(value).replace("\n", "").replace(",", "").replace(".", "").isdigit():
                    continue
                cite = {"table_id": table_id, "row": row, "column": col, "value": value}
                assert check_table_citation(ci, cite) is None, cite
                assert cite_table(table_id, row, col, value).get("value") == value, cite
                cell_count += 1
    assert cell_count == 116, cell_count

    checked = []
    for index, plate in enumerate(PLATES):
        result = per_unit(spec, {"work_type": "Rolling 및 Edge 가공", "plate_size": plate, "quantity": "1"})
        assert result["status"] == "computed" and result["unit_basis"]["per"] == "1매", (plate, result)
        lines = {x["name"]: Fraction(x["exact"]) for x in result["unit_lines"]}
        expected = {"일반기계운전사\n(윈치운전)": Fraction(PLATE_RATES[index][0]),
                    "플랜트\n제관공": Fraction(PLATE_RATES[index][1]), "특별인부": Fraction(PLATE_RATES[index][2])}
        assert lines == expected, (plate, lines, expected)
        checked.append({"work_type": "rolling_edge", "input": plate, "status": "computed", "rates": {k: str(v) for k, v in lines.items()}})

    fabrication = per_unit(spec, {"work_type": "금긋기 및 절단가공", "quantity": "1"})
    assert fabrication["status"] == "computed" and fabrication["unit_basis"]["per"] == "1ton"
    assert [(x["name"], Fraction(x["exact"])) for x in fabrication["unit_lines"]] == [
        ("플랜트제관공", Fraction("0.437")), ("플랜트제관공", Fraction("1.161")), ("플랜트제관공", Fraction("0.318"))]
    checked.append({"work_type": "mark_and_cut", "status": "computed", "subprocess_rates": ["0.437", "1.161", "0.318"], "unit": "ton"})

    transport = per_unit(spec, {"work_type": "운반조작", "is_special_material": False, "quantity": "1"})
    assert transport["status"] == "computed" and transport["unit_basis"]["per"] == "1ton"
    assert {x["name"]: Fraction(x["exact"]) for x in transport["unit_lines"]} == {
        "비계공": Fraction("0.073"), "건설기계운전(조/대)": Fraction("0.037"), "특별인부": Fraction("0.073")}
    special = per_unit(spec, {"work_type": "운반조작", "is_special_material": True, "quantity": "1"})
    assert special["status"] == "blocked" and "40~50%" in special["reason"]
    checked.extend([{"work_type": "transport", "status": transport["status"], "rates": ["0.073", "0.037", "0.073"]},
                    {"work_type": "transport_special_material", "status": special["status"], "source_range_retained": True}])

    for ci_cap, cap in enumerate(CAPS):
        result = per_unit(spec, {"work_type": "탱크조립설치", "tank_capacity": cap,
                                 "welding_length_change": False, "quantity": "1"})
        assert result["status"] == "computed" and result["unit_basis"]["per"] == "1ton", (cap, result)
        got = {x["name"]: Fraction(x["exact"]) for x in result["unit_lines"]}
        expected = {trade: Fraction(TANK_RATES[ri][ci_cap]) for ri, trade in enumerate(TANK_TRADES)}
        assert got == expected, (cap, got, expected)
        checked.append({"work_type": "tank_install", "capacity": cap.replace("\n", " "), "status": "computed",
                        "trade_rates": {k: str(v) for k, v in got.items()}})
    weld_change = per_unit(spec, {"work_type": "탱크조립설치", "tank_capacity": CAPS[0],
                                  "welding_length_change": True, "quantity": "1"})
    assert weld_change["status"] == "blocked" and "산식·계수" in weld_change["reason"]
    checked.append({"work_type": "tank_install_weld_length_change", "status": "blocked", "source_rule_retained": True})

    blocked_by_field = defaultdict(list)
    for item in spec.get("blocked", []):
        condition = item.get("blocked_if")
        if condition:
            blocked_by_field[condition["input"]].append(condition)
    choices = [_values(field, blocked_by_field[field["name"]], []) for field in spec["inputs"]]
    preflight_counts = Counter(); base_computed = False
    for index, values in enumerate(itertools.islice(itertools.product(*choices), 64)):
        inputs = dict(zip((f["name"] for f in spec["inputs"]), values))
        result = per_unit(spec, inputs); status = result.get("status")
        if index == 0:
            base_computed = status == "computed"
        assert status in ("computed", "blocked"), (inputs, result)
        preflight_counts[status] += 1
    assert base_computed and sum(preflight_counts.values()) == 64, preflight_counts

    hit = {"rank": 1, "section_no": "13-4-3", "division": "기계설비",
           "section": f"13-4-3 {spec['title']}", "page": 765, "table_id": "p821-t2",
           "text": spec["title"], "chunk_id": "p821-t2"}
    section_map = {("기계설비", "13-4-3"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 765, "division": "기계설비"})), \
            patch.object(estimate_tools, "specs_by_section", return_value=section_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=section_map):
        session = estimate_tools.new_estimate("저장탱크 설치")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(q["field"] == "work_type" for q in first.get("missing", [])), first
        estimate_tools.set_conditions(session, "Rolling 및 Edge 가공", values={
            "work_type": {"value": "Rolling 및 Edge 가공", "evidence": "원문 공종 선택"}}, source="answer")
        estimate_tools.set_conditions(session, PLATES[0], values={
            "plate_size": {"value": PLATES[0], "evidence": "원문 철판 규격"}}, source="answer")
        asked = estimate_tools.compute_labor(session)
        q = next(item for item in asked.get("missing", []) if item["field"] == "quantity")
        assert q.get("unit") == "매", q
        set_quantity = estimate_tools.set_conditions(session, "2매", quantity={"value": "2", "unit": "매", "evidence": "2매"}, source="text")
        assert not set_quantity.get("rejected"), set_quantity
        estimate_flow = estimate_tools.compute_labor(session)
        assert estimate_flow.get("status") == "ok", estimate_flow
        assert estimate_flow["data"]["unit_basis"]["per"] == "1매"
        assert len(estimate_flow["data"]["unit_lines"]) == 3

    validation = validate_one(SPEC, ROOT / "data/drafts/specs", ci, None)
    assert not validation.get("issues"), validation
    audit = {"id": spec["id"], "status": "source_axes_and_task_basis_verified",
             "source": {"printed_pages": [765, 766], "images": [str(p.relative_to(ROOT)) for p in IMAGES],
                        "pdf_sha256": sha(PDF), "image_sha256": [sha(p) for p in IMAGES], "numeric_cells_checked": cell_count,
                        "coverage": {"p821-t2": 36, "p822-t0": 4, "p822-t1": 4, "p822-t2": 72}},
             "runtime": {"routes_checked": len(checked), "routes": checked,
                         "execution_preflight": {"checked": sum(preflight_counts.values()),
                                                 "status_counts": dict(preflight_counts),
                                                 "first_combination_computed": base_computed},
                         "consultation_flow": {"status": estimate_flow["status"],
                                               "quantity_unit_question": q["unit"],
                                               "unit_basis": estimate_flow["data"]["unit_basis"]["per"],
                                               "rates": {x["name"]: x["exact"] for x in estimate_flow["data"]["unit_lines"]}},
                         "validation_issues": validation.get("issues", [])},
             "unresolved_source_rules": ["special-material transport rate is an unresolved 40–50% range",
                                         "tank assembly welding labor changes with weld length but the source gives no equation or coefficient",
                                         "painting, stairs/railings, fire facilities, and auxiliary piping are separate or excluded source scopes"],
             "rule_scope": {"verified": "all 116 numeric rate and total cells; all four task-specific table axes; 9 plate, 3 fabrication subprocess, 3 transport, and 72 tank-install rates",
                            "all_rules_fully_verified": False},
             "spec_sha256": sha(SPEC), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
             "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "numeric_cells_checked": cell_count,
                      "routes_checked": len(checked), "validation_issues": validation.get("issues", []),
                      "unresolved_rules": len(audit["unresolved_source_rules"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

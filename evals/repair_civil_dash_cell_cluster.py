"""Restore exact dash exclusions for four civil per-unit source tables.

The PDF checker compares every rate cell in the four restored tables against
the original PDF grid, then exercises every distinct resource route affected
by the dash cells. It never interprets a dash as a zero rate.
"""
from __future__ import annotations

from fractions import Fraction
import copy
import json
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TARGETS = {
    "2-3-1": [
        {"trade": "특별인부", "when": {"work_type": "복토"},
         "cite": {"table_id": "p390-t2", "row": "특별인부", "column": "복토", "value": "-"}},
        {"trade": "굴삭기", "when": {"work_type": "식생매트설치"},
         "cite": {"table_id": "p390-t2", "row": "굴삭기", "column": "식생매트설치", "value": "-"}},
    ],
    "3-4-3": [
        {"trade": "굴착기(0.6㎥)", "when": {"section_type": "공동구"},
         "cite": {"table_id": "p399-t3", "row": "굴착기(0.6㎥)", "column": "공동구", "value": "-"}},
        {"trade": "굴착기(0.2㎥)", "when": {"section_type": "바닥/인버트"},
         "cite": {"table_id": "p399-t3", "row": "굴착기(0.2㎥)", "column": "바닥/인버트", "value": "-"}},
    ],
    "6-7-3": [
        {"trade": "크레인", "when": {"pipe_diameter": size}, "cite": [
            {"table_id": "p432-t0", "row": size, "column": "크레인(hr) 비압력관", "value": "-"},
            {"table_id": "p432-t0", "row": size, "column": "크레인(hr) 압력관", "value": "-"},
        ]}
        for size in ("150", "200")
    ],
    "6-8-4": [
        {"trade": "크레인", "when": {"pipe_diameter": size},
         "cite": {"table_id": "p438-t1", "row": size, "column": "크레인", "value": "-"}}
        for size in ("80", "100")
    ],
}


def read_spec(section: str) -> tuple[Path, dict]:
    path = ROOT / "data/drafts/specs/토목" / f"{section}.json"
    return path, json.loads(path.read_text(encoding="utf8"))


def add_rules(section: str) -> None:
    path, pkg = read_spec(section)
    params = pkg["draft"]["quantity_model"]["params"]
    if section == "6-7-3":
        params["unit_rate_table"]["column_match_mode"] = "token"
    existing = params.setdefault("excluded_resources", [])
    for rule in TARGETS[section]:
        if rule not in existing:
            existing.append(copy.deepcopy(rule))
    path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def check_source_grid(document: fitz.Document) -> int:
    checked = 0
    # p390-t2 has two resource rows and two task columns under merged headers.
    grid = document[389].find_tables().tables[2].extract()
    expected_231 = {
        ("특별인부", "식생매트설치"): "0.014", ("특별인부", "복토"): "-",
        ("보통인부", "식생매트설치"): "0.003", ("보통인부", "복토"): "0.005",
        ("굴삭기", "식생매트설치"): "-", ("굴삭기", "복토"): "0.031",
    }
    rows = ["특별인부", "보통인부", "굴삭기"]
    for i, trade in enumerate(rows):
        values = grid[2][3].splitlines() if i < 2 else [grid[3][3]]
        other = grid[2][4].splitlines() if i < 2 else [grid[3][4]]
        for work, actual in zip(("식생매트설치", "복토"), (values[i] if i < 2 else values[0], other[i] if i < 2 else other[0])):
            assert expected_231[(trade, work)] == actual.strip(), (trade, work, actual)
            checked += 1
    spec = read_spec("2-3-1")[1]["draft"]["tables"][0]
    assert spec["values"] == {
        "특별인부": {"식생매트설치": "0.014", "복토": "-"},
        "보통인부": {"식생매트설치": "0.003", "복토": "0.005"},
        "굴삭기": {"식생매트설치": "-", "복토": "0.031"},
    }

    # p399-t3 table has labor rows grouped in one cell and four machine rows.
    grid = document[398].find_tables().tables[3].extract()
    expected_343 = {
        "특별인부": ("0.014", "0.009"), "보통인부": ("0.134", "0.085"),
        "굴착기(0.2㎥)": ("0.141", "-"), "굴착기(0.6㎥)": ("-", "0.085"),
        "물탱크(살수차)": ("0.123", "0.074"), "동력분무기": ("0.123", "0.074"),
    }
    parsed = {}
    for trade, values in zip(("특별인부", "보통인부"), zip(grid[2][3].splitlines(), grid[2][4].splitlines())):
        parsed[trade] = tuple(value.strip() for value in values)
    machine_names = ["굴착기(0.2㎥)", "굴착기(0.6㎥)", "물탱크(살수차)", "동력분무기"]
    left, right = grid[3][3].splitlines(), grid[3][4].splitlines()
    parsed.update({name: (a.strip(), b.strip()) for name, a, b in zip(machine_names, left, right)})
    assert parsed == expected_343, (parsed, expected_343)
    table = read_spec("3-4-3")[1]["draft"]["tables"][0]["values"]
    for trade, values in expected_343.items():
        assert tuple(table[trade][work] for work in ("공동구", "바닥/인버트")) == values
        checked += 2

    # p432-t0 has two exact pipe-type columns beneath each merged trade header.
    grid = document[431].find_tables().tables[0].extract()
    sizes = grid[2][0].splitlines()
    rate_columns = [column.splitlines() for column in grid[2][1:]]
    table = read_spec("6-7-3")[1]["draft"]["tables"][0]["values"]
    labels = ["배관공(수도)(인) 비압력관", "배관공(수도)(인) 압력관",
              "보통인부(인) 비압력관", "보통인부(인) 압력관",
              "크레인(hr) 비압력관", "크레인(hr) 압력관"]
    assert len(sizes) == 22 and all(len(column) == 22 for column in rate_columns)
    for row_index, raw_size in enumerate(sizes):
        size = raw_size.strip()
        row = table.get(size)
        assert row is not None, size
        for label, column in zip(labels, rate_columns):
            assert row[label] == column[row_index].strip(), (size, label, row[label], column[row_index])
            checked += 1

    # p438-t1 has one rate per resource and size; p438-t0/t2 are separate crane specifications.
    grid = document[437].find_tables().tables[1].extract()
    sizes, *rate_columns = [cell.splitlines() for cell in grid[1]]
    table = read_spec("6-8-4")[1]["draft"]["tables"][0]["values"]
    assert len(sizes) == 14 and all(len(column) == 14 for column in rate_columns)
    for i, size in enumerate(sizes):
        row = table[size.strip()]
        for label, column in zip(("배관공(수도)", "보통인부", "크레인"), rate_columns):
            assert row[label] == column[i].strip(), (size, label, row[label], column[i])
            checked += 1
    return checked


def check_routes() -> dict:
    sys.path.insert(0, str(ROOT))
    from backend.agent.tools.calc.per_unit import per_unit

    routes = 0
    dash_blocks = 0

    def verify_source_output(result: dict, table_id: str, table_values: dict) -> None:
        assert result["status"] == "computed", result
        for line in result["unit_lines"]:
            citation = line["citations"][0]
            assert citation["internal_id"] == table_id
            expected = table_values[citation["row"]][citation["column"]]
            assert expected == citation["value"]
            assert line["exact"] == str(Fraction(expected)), (line, expected)
        assert result["provenance"]["quantity"]
        for excluded in result["provenance"].get("excluded_resources", []):
            assert excluded["citations"] and all(cite["value"] == "-" for cite in excluded["citations"]), excluded

    # Each work type is exercised; the source dash must omit only that exact resource.
    pkg = read_spec("2-3-1")[1]["draft"]
    for work, expected_names in (("식생매트설치", {"특별인부", "보통인부"}),
                                 ("복토", {"보통인부", "굴삭기"})):
        result = per_unit(pkg, {"work_type": work, "area": "100"})
        verify_source_output(result, "p390-t2", read_spec("2-3-1")[1]["draft"]["tables"][0]["values"])
        assert {line["name"] for line in result["unit_lines"]} == expected_names, result
        assert len(result.get("provenance", {}).get("excluded_resources", [])) == 1
        dash_blocks += 1; routes += 1
    pkg = read_spec("3-4-3")[1]["draft"]
    for section, expected_names in (("공동구", {"특별인부", "보통인부", "굴착기(0.2㎥)", "물탱크(살수차)", "동력분무기"}),
                                    ("바닥/인버트", {"특별인부", "보통인부", "굴착기(0.6㎥)", "물탱크(살수차)", "동력분무기"})):
        result = per_unit(pkg, {"section_type": section, "area": "100"})
        verify_source_output(result, "p399-t3", read_spec("3-4-3")[1]["draft"]["tables"][0]["values"])
        assert {line["name"] for line in result["unit_lines"]} == expected_names, result
        assert len(result.get("provenance", {}).get("excluded_resources", [])) == 1
        dash_blocks += 1; routes += 1
    pkg = read_spec("6-7-3")[1]["draft"]
    for size in ("150", "200", "250"):
        for pipe_type in ("비압력관", "압력관"):
            result = per_unit(pkg, {"pipe_diameter": size, "pipe_type": pipe_type,
                                    "quantity": "2", "crane_size": "크레인 5ton급"})
            verify_source_output(result, "p432-t0", read_spec("6-7-3")[1]["draft"]["tables"][0]["values"])
            lines = [line for line in result["unit_lines"] if line["name"] == "크레인"]
            rate = read_spec("6-7-3")[1]["draft"]["tables"][0]["values"][size][f"크레인(hr) {pipe_type}"]
            if rate == "-":
                assert not lines and any(x["trade"] == "크레인" for x in result.get("provenance", {}).get("excluded_resources", [])), result
                dash_blocks += 1
            else:
                assert len(lines) == 1 and lines[0]["exact"] == str(Fraction(rate)), result
            routes += 1
    pkg = read_spec("6-8-4")[1]["draft"]
    for size in ("80", "100", "150", "200", "250", "300", "350", "400", "450", "500", "600", "700", "800", "900"):
        result = per_unit(pkg, {"pipe_diameter": size, "quantity": "3"})
        verify_source_output(result, "p438-t1", read_spec("6-8-4")[1]["draft"]["tables"][0]["values"])
        lines = [line for line in result["unit_lines"] if line["name"] == "크레인"]
        expected_rate = read_spec("6-8-4")[1]["draft"]["tables"][0]["values"][size]["크레인"]
        if expected_rate == "-":
            assert not lines and any(x["trade"] == "크레인" for x in result.get("provenance", {}).get("excluded_resources", [])), result
            dash_blocks += 1
        else:
            assert len(lines) == 1 and lines[0]["exact"] == str(Fraction(expected_rate)), result
        routes += 1
    return {"exact_runtime_routes": routes, "dash_route_checks": dash_blocks}


def main() -> None:
    for section in TARGETS:
        add_rules(section)
    with fitz.open(PDF) as document:
        source_cells = check_source_grid(document)
    route_results = check_routes()
    print(json.dumps({"status": "pass", "root_cause": "source dash cells were treated as numeric unit rates instead of exact conditional resource exclusions",
                      "sections": list(TARGETS), "independent_pdf_cells_compared": source_cells,
                      **route_results, "full_rule_verification": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

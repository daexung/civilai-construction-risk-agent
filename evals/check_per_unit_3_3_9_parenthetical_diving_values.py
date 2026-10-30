"""Check original source cells and the note-defined parenthetical diver rates."""
import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_draft_executability import CALCULATORS, _values
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table, resolve_cites

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE = ROOT / "evals/runtime_validation/source-p130-3-3-9.png"
AUDIT = ROOT / "evals/runtime_validation/per-unit-3-3-9-parenthetical-values-2026-10-19.json"
RAW = {
    "폭약": ("0.96", "0.92"), "뇌관": ("3.0", "1.2"), "비트": ("0.009", "0.006"),
    "화약취급공": ("0.11", "0.07"), "착암공": ("0.094(0)", "0.064(0)"),
    "보통인부": ("0.19", "0.11"), "잠수부": ("0.5(1.0)", "0.3(0.6)"),
    "소형브레이커": ("0.474", "0.313"), "공기압축기": ("0.158", "0.104"),
}
BLAST = ("우물통발파", "우물통발파 이외")
METHODS = ("일반 천공", "잠수부 천공")
KINDS = {"폭약": "material", "뇌관": "material", "비트": "material",
         "화약취급공": "labor", "착암공": "labor", "보통인부": "labor",
         "잠수부": "labor", "소형브레이커": "equipment", "공기압축기": "equipment"}
UNITS = {"폭약": "kg", "뇌관": "개", "비트": "개", "화약취급공": "인", "착암공": "인",
         "보통인부": "인", "잠수부": "조", "소형브레이커": "hr", "공기압축기": "hr"}

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def value(raw, method):
    if "(" not in raw:
        return Fraction(raw)
    primary, parenthetical = raw[:-1].split("(", 1)
    return Fraction(parenthetical if method == "잠수부 천공" else primary)

def main():
    path = ROOT / "data/drafts/specs/공통/3-3-9.json"
    spec = json.loads(path.read_text(encoding="utf8"))["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p130-t0")
    cells = []
    for row, pair in RAW.items():
        for column, raw in zip(BLAST, pair):
            assert table["values"][row][column] == raw, (row, column)
            citation = cite_table("p130-t0", row, column, raw)
            assert citation.get("value") == raw and citation.get("pdf_page") == 130, citation
            cells.append({"row": row, "column": column, "raw_source_value": raw})
    assert len(cells) == 18
    doc = pymupdf.open(PDF)
    doc[129].get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), alpha=False).save(IMAGE)
    source_text = doc[129].get_text("text")
    assert "3-3-9" in source_text and "잠수부 천공시의 품" in source_text

    routes = []
    for blast_type, method in itertools.product(BLAST, METHODS):
        inp = {"blast_type": blast_type, "drilling_method": method,
               "water_depth": "2.5m 이상~8m 미만", "volume": "1"}
        result = per_unit(spec, inp)
        assert result.get("status") == "computed", (inp, result)
        lines = {x["name"]: x for x in result["unit_lines"]}
        assert set(lines) == set(RAW), (inp, lines.keys())
        col_idx = BLAST.index(blast_type)
        for name, pair in RAW.items():
            line = lines[name]
            expected = value(pair[col_idx], method)
            assert Fraction(line["exact"]) == expected, (inp, name, expected, line)
            assert line["kind"] == KINDS[name]
            assert line["unit"] == f"{UNITS[name]}/㎥", (inp, name, line["unit"])
            assert line["citations"][0].get("value") == pair[col_idx]
            if "(" in pair[col_idx]:
                assert line["citations"][1].get("quote") == "( )내는 잠수부 천공시의 품이다."
                assert line["rule"].find("괄호 값") >= 0, (inp, name, line["rule"])
        routes.append({"blast_type": blast_type, "drilling_method": method,
                       "status": "computed", "selected_parenthetical_mode": "parenthetical" if method == "잠수부 천공" else "primary",
                       "resource_rates": {name: str(value(pair[col_idx], method)) for name, pair in RAW.items()}})

    blocked_by_field = {f["name"]: [] for f in spec["inputs"]}
    for rule in spec.get("blocked", []):
        for c in rule.get("blocked_if_all", ([rule["blocked_if"]] if rule.get("blocked_if") else [])):
            blocked_by_field[c["input"]].append(c)
    params = spec["quantity_model"]["params"]
    adjustments = params.get("surcharges", []) + params.get("note_adjustments", [])
    choices = [_values(f, blocked_by_field[f["name"]], adjustments) for f in spec["inputs"]]
    statuses = []
    preflight = []
    for vals in itertools.product(*choices):
        inp = dict(zip((f["name"] for f in spec["inputs"]), vals))
        result = CALCULATORS["per_unit"](spec, inp)
        statuses.append(result.get("status"))
        preflight.append({"inputs": inp, "status": result.get("status"), "reason": result.get("reason")})
    if not (len(statuses) == 16 and statuses.count("computed") == 4 and statuses.count("blocked") == 12):
        print(json.dumps(preflight, ensure_ascii=True))
    assert len(statuses) == 16 and statuses.count("computed") == 4 and statuses.count("blocked") == 12, {"n": len(statuses), "statuses": {s: statuses.count(s) for s in set(statuses)}}
    selector_citations = resolve_cites(spec["quantity_model"]["params"]["unit_rate_table"]["parenthetical_value_selector"]["cite"])
    audit = {"id": spec["id"], "status": "parenthetical_source_values_and_routes_verified",
             "source": {"physical_page": 130, "printed_page": 74, "visual_image": str(IMAGE.relative_to(ROOT)),
                        "pdf_sha256": sha(PDF), "image_sha256": sha(IMAGE), "unique_cells_checked": len(cells), "cells": cells,
                        "interpretation": "The original note explicitly states parenthesized cell values are for diver drilling. General drilling uses the value before parentheses; diver drilling uses the parenthetical value."},
             "runtime": {"exact_blast_method_routes": len(routes), "routes": routes, "execution_preflight_combinations": len(statuses),
                         "preflight_statuses": {"computed": statuses.count("computed"), "blocked": statuses.count("blocked")},
                         "water_depth_preflight": {d: {"computed": sum(x["status"] == "computed" and x["inputs"]["water_depth"] == d for x in preflight),
                                                       "blocked": sum(x["status"] == "blocked" and x["inputs"]["water_depth"] == d for x in preflight)}
                                                    for d in next(f["allowed_values"] for f in spec["inputs"] if f["name"] == "water_depth")},
                         "diving_note_citations": selector_citations},
             "scope": "All 18 source cells in p130-t0 were checked, including the two parenthetical resources across both blast columns. Four exact blast/method outputs were verified at 2.5-8m. The optional <2.5m reduction, optional 8-15m increase, and 15m+ unspecified rule remain blocked; they are not counted as resolved.",
             "spec_sha256": sha(path), "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"cells": len(cells), "routes": len(routes), "preflight": len(statuses), "audit": str(AUDIT.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()

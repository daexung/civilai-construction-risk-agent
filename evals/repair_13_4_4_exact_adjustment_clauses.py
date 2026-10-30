"""Recover exact source adjustment clauses from the flattened 13-4-4 note."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import _exact_text
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/13-4-4.json"
BASE = {"기계산업기사": "0.30", "철골공": "4.98", "비계공": "3.27",
        "기계설비공": "0.82", "용접공": "0.80"}
WEIGHT_FACTORS = {"0.5ton 미만": Fraction("1.3"), "0.5~1ton 미만": Fraction("1.15"),
                  "1~5ton": Fraction("1"), "5ton 이상": Fraction("0.8")}


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p825-t0")
    assert {name: table["values"][name]["수량"] for name in BASE} == BASE
    chunk = next(json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl")
                 .read_text(encoding="utf-8").splitlines()
                 if line.strip() and json.loads(line).get("chunk_id") == "p825-t0")
    source_text = chunk["text"]
    source_phrases = ["0.5ton 미만은 30% 가산", "0.5∼1ton 미만은 15% 가산",
                      "5ton 이상은 20% 감", "검사 및 교정이 필요한 경우에 기술관리를 제외한 본 품의 10%를 가산한다",
                      "Steel Stack 등 ton당 용접장(6㎜ Fillet 환산)이 30m를 초과하는 경우 20%를 가산한다"]
    for phrase in source_phrases:
        assert phrase in source_text, phrase

    clauses = draft["quantity_model"]["params"]["surcharges"]
    assert len(clauses) == len(source_phrases), (len(clauses), len(source_phrases))
    for clause, phrase in zip(clauses, source_phrases):
        clause["application_cite"] = {"chunk_id": "p825-t0", "quote": phrase}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    scenarios = [("weight", weight, False, False, factor)
                 for weight, factor in WEIGHT_FACTORS.items()]
    scenarios += [("inspection", "1~5ton", True, False, None),
                  ("weld_length", "1~5ton", False, True, None)]
    for label, weight, inspection, weld, factor in scenarios:
        inputs = {"quantity": "1", "weight_per_unit": weight,
                  "inspection_needed": inspection, "weld_length_over_30m": weld}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (label, inputs, result)
        actual = {line["name"]: line["applied"] for line in result["unit_lines"]}
        if label == "weight":
            expected = {name: _exact_text(Fraction(value) * factor) for name, value in BASE.items()}
            wanted_quote = {
                "0.5ton 미만": source_phrases[0], "0.5~1ton 미만": source_phrases[1],
                "1~5ton": None, "5ton 이상": source_phrases[2],
            }[weight]
            if wanted_quote:
                assert all(any(cite.get("quote") == wanted_quote for cite in line["citations"])
                           for line in result["unit_lines"])
        elif label == "inspection":
            expected = {name: _exact_text(Fraction(value) * (Fraction(1) if name == "기계산업기사"
                                                                else Fraction("1.1")))
                        for name, value in BASE.items()}
            assert all(any(cite.get("quote") == source_phrases[3] for cite in line["citations"])
                       for line in result["unit_lines"] if line["name"] != "기계산업기사")
        else:
            expected = {name: _exact_text(Fraction(value) * Fraction("1.2")) for name, value in BASE.items()}
            assert all(any(cite.get("quote") == source_phrases[4] for cite in line["citations"])
                       for line in result["unit_lines"])
        assert actual == expected, (label, expected, actual)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), (label, priced)
        cases.append({"case": label, "inputs": inputs, "expected_rates": expected,
                      "actual_rates": actual, "price_status": priced["status"],
                      "price_unit_quantities": {line["name"]: line["quantity"]
                                                 for line in priced["lines"]}})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path), file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/기계설비/13-4-4.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    artifact = {"id": ident, "physical_page": 825, "printed_page": 769,
                "source_visual": "tmp/13-4-4-source-p825.png", "original_table_rates": BASE,
                "exact_source_phrases": source_phrases, "calculation_and_price_cases": cases,
                "focused_validation_ok": validation["ok"],
                "scope": "individual weight, inspection and weld-length clauses verified separately; combined modifier order and all-rule certification not claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-13-4-4-adjustment-clause-source-audit-2026-10-19.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "source_rate_cells": len(BASE), "separate_scenarios": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

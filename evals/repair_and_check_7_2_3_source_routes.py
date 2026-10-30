"""Reconstruct the 7-2-3 sparse table axes and source-scoped conditions."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/토목/7-2-3.json"
CHUNKS_PATH = ROOT / "data/processed/chunks.all.jsonl"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-7-2-3-source-routes-2026-10-19.json"
TABLE_ID = "p446-t1"
SMALL = "수량 0.03㎥ 이하\n덤프트럭+굴착기 투하"
LARGE = "수량 0.1㎥ 이상\n크레인 투하"
SOURCE = {"잠수부": ["-", "0.09"], "특별인부": ["-", "0.13"],
          "보통인부": ["0.008", "0.13"]}


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    table = next(item for item in spec["tables"] if item["id"] == TABLE_ID)
    method_keys = [SMALL, LARGE]
    assert rate["table"] == TABLE_ID
    rate["row_input"] = None  # Source rows are the resource/trade labels.
    for trade, values in SOURCE.items():
        actual = [table["values"].get(trade, {}).get(method, "-") for method in method_keys]
        assert actual == values, (trade, actual, values)

    # The source prints dashes for diver and special labor in the small
    # dump-truck/loader column, and a separate note excludes divers on the
    # above-water portion. Encode each as a source-backed resource omission.
    params["note_adjustments"] = [item for item in params.get("note_adjustments", [])
                                  if not (item.get("when") == {"is_underwater": False}
                                          and "잠수부" in item.get("change", ""))]
    exclusions = [
        {"trade": "잠수부", "when": {"method": SMALL},
         "cite": {"table_id": TABLE_ID, "row": "잠수부", "column": SMALL, "value": "-"}},
        {"trade": "특별인부", "when": {"method": SMALL},
         "cite": {"table_id": TABLE_ID, "row": "특별인부", "column": SMALL, "value": "-"}},
        {"trade": "잠수부", "when": {"is_underwater": False},
         "cite": {"chunk_id": "p446-x10", "quote": "④ 수상부분은 잠수부를 계상하지 않는다."}},
    ]
    params["excluded_resources"] = exclusions

    steep_condition = {"blocked_if_all": [
        {"input": "method", "op": "==", "value": SMALL},
        {"input": "slope", "op": "==", "value": "1:1보다 급함"},
    ]}
    blocked = spec.setdefault("blocked", [])
    steep_entry = {**steep_condition,
        "condition": "0.03㎥ 이하 규격에서 경사도 1:1보다 급한 경우",
        "reason": "원문에서 별도 계상하도록 하며 별도 산정 규칙이 없어 자동 산출을 보류한다.",
        "source": "p446-x10 [주]②",
        "cite": {"chunk_id": "p446-x10",
                 "quote": "② 0.03㎥ 이하 규격에서 경사도 1:1보다 급한 경우, 별도 계상한다."}}
    # Replace the earlier broad single-axis block with the exact condition
    # stated by the note: only the <=0.03㎥ method at a steep slope is separate.
    blocked[:] = [entry for entry in blocked if not (
        entry.get("source") == "p446-x10 주 ②"
        and "0.03㎥ 이하 규격에서 경사도" in entry.get("condition", "")
    )]
    blocked.append(steep_entry)

    chunks = [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf8").splitlines()
              if line.strip()]
    chunk = next(item for item in chunks if item.get("chunk_id") == TABLE_ID)
    restored = ("\n[원문 표 셀 복원: PDF 446쪽(인쇄 390쪽), 7-2-3 육상투하] "
                "잠수부 | 수량 0.03㎥ 이하 덤프트럭+굴착기 투하 -; "
                "특별인부 | 수량 0.03㎥ 이하 덤프트럭+굴착기 투하 -."
                "\n[주] ② 0.03㎥ 이하 규격에서 경사도 1:1보다 급한 경우 별도 계상; "
                "④ 수상부분은 잠수부를 계상하지 않는다.")
    if restored.strip() not in chunk["text"]:
        chunk["text"] = chunk["text"].rstrip() + restored
        CHUNKS_PATH.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in chunks)
                               + "\n", encoding="utf8")
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    # Check every source axis together with both boolean note states, both
    # slope classes, and two quantities. Only the steep/small combination is
    # blocked by the explicit separate-account source rule.
    routes = outputs = blocked_routes = 0
    for method_index, method in enumerate(method_keys):
        for slope in ["1:1 이하", "1:1보다 급함"]:
            for underwater in [True, False]:
                for quantity in ["10", "20"]:
                    inputs = {"method": method, "slope": slope,
                              "is_underwater": underwater, "volume": quantity}
                    result = per_unit(spec, inputs)
                    if method == SMALL and slope == "1:1보다 급함":
                        assert result["status"] == "blocked", result
                        blocked_routes += 1
                        continue
                    assert result["status"] == "computed", (inputs, result)
                    present = {trade: Fraction(values[method_index]) / 10
                               for trade, values in SOURCE.items()
                               if values[method_index] != "-"
                               and not (trade == "잠수부" and underwater is False)}
                    got = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
                    assert got == present, (inputs, got, present)
                    for line in result["unit_lines"]:
                        cites = [cite for cite in line["citations"]
                                 if cite.get("internal_id") == TABLE_ID]
                        assert len(cites) == 1
                        assert cites[0].get("row") == line["name"]
                        assert cites[0].get("value") == SOURCE[line["name"]][method_index]
                        assert Fraction(line["exact"]) * Fraction(quantity) == (
                            Fraction(SOURCE[line["name"]][method_index]) * Fraction(quantity) / 10)
                    excluded = result["provenance"]["excluded_resources"]
                    if not underwater and method == LARGE:
                        diver = [item for item in excluded if item["trade"] == "잠수부"]
                        assert len(diver) == 1
                        assert any(c.get("quote") == "④ 수상부분은 잠수부를 계상하지 않는다."
                                       for c in diver[0]["citations"])
                    routes += 1
                    outputs += len(got)

    # The source exception is specifically the steep small-size path.
    assert routes == 12 and outputs == 24 and blocked_routes == 4
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(CHUNKS_PATH),
                              file_sha256(CHUNKS_PATH))
    assert not validation["format_issues"], validation["format_issues"]
    assert not validation["citation_issues"], validation["citation_issues"]
    audit = {"status": "pass", "section": "토목/7-2-3", "table_id": TABLE_ID,
             "source": "Original PDF p.446 / printed p.390, rendered page independently inspected",
             "independent_source_cells": 6, "source_dash_cells": 2,
             "restored_dash_cells": 2, "exact_calculated_routes": routes,
             "exact_rate_outputs_with_citations": outputs,
             "source_separate_account_blocked_routes": blocked_routes,
             "quantities_tested": ["10", "20"],
             "format_preflight": "pass", "citation_preflight": "pass",
             "full_rule_verification": False}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

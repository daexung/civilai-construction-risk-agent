"""Wire 9-14-1/2 area, registration and region coefficients from source tables."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one


CONFIG = {
    "9-14-1": {
        "base": "p604-t0", "area_table": "p605-t0", "registration_table": "p605-t1",
        "region_table": "p605-t2", "quantity": "quantity", "land": "land_type",
        "region": "region_type", "area": "area", "base_by_land": {"토지": "300", "임야": "3000"},
        "base_quote_id": "p605-x0", "base_quote": "본 품은 1필지당 토지는 300㎡, 임야는 3,000㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다.",
        "n_cite": ("p605-x3", "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"),
        "land_cite": ("p605-x3", "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."),
        "region_cite": ("p605-x7", "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."),
        "appraisal_input": "appraisal_requested", "appraisal_cite": ("p605-x10", "본 품의 측량결과에 대한 설명을 부가한 감정도 및 감정서 발급을 요청할 경우에는 추가 품을 가산 적용할 수 있다."),
        "physical": [605], "images": ["tmp/focus-605.png"],
        "rates": ["0.73", "0.77", "0.47"],
        "cases": [
            ({"quantity": "1", "land_type": "토지", "area": "1500", "region_type": "동(구)", "appraisal_requested": False}, Fraction(2), ["1.46", "1.54", "0.94"]),
            ({"quantity": "2", "land_type": "임야", "area": "3001", "region_type": "읍", "appraisal_requested": False}, Fraction(8, 5), ["1.168", "1.232", "0.752"]),
            ({"quantity": "1", "land_type": "토지", "area": "300", "region_type": "면", "appraisal_requested": False}, Fraction(1), ["0.73", "0.77", "0.47"]),
            ({"quantity": "1", "land_type": "토지", "area": "1500", "region_type": "동(구)", "appraisal_requested": True}, None, None)
        ]
    },
    "9-14-2": {
        "base": "p606-t0", "area_table": "p606-t1", "region_table": "p606-t2",
        "quantity": "parcels", "region": "region_type", "area": "area", "base_area": "300",
        "base_quote_id": "p606-x10", "base_quote": "본 품은 1필지당 300㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다.",
        "n_cite": ("p606-x14", "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"),
        "region_cite": ("p606-x14", "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."),
        "appraisal_input": "appraisal_requested", "appraisal_cite": ("p607-x0", "가산 적용할 수 있다."),
        "physical": [606, 607], "images": ["tmp/focus-606.png", "tmp/focus-607.png"],
        "rates": ["0.58", "0.62", "0.34"],
        "cases": [
            ({"parcels": "1", "area": "1500", "region_type": "구(동지역)", "appraisal_requested": False}, Fraction(2), ["1.16", "1.24", "0.68"]),
            ({"parcels": "2", "area": "300", "region_type": "면", "appraisal_requested": False}, Fraction(1), ["0.58", "0.62", "0.34"]),
            ({"parcels": "1", "area": "301", "region_type": "읍", "appraisal_requested": False}, Fraction(7, 5), ["0.812", "0.868", "0.476"]),
            ({"parcels": "1", "area": "1500", "region_type": "구(동지역)", "appraisal_requested": True}, None, None)
        ]
    }
}


def cite(pair):
    return {"chunk_id": pair[0], "quote": pair[1]}


def repair(section, c):
    path = ROOT / f"data/drafts/specs/토목/{section}.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    if c["appraisal_input"] not in {item["name"] for item in draft.get("inputs", [])}:
        draft["inputs"].append({"name": c["appraisal_input"], "type": "boolean",
                                "allowed_values": [True, False], "unit": None, "required": True,
                                "ask": "측량결과에 대한 설명을 부가한 감정도 및 감정서 발급을 요청합니까?",
                                "source": f"PDF {c['physical'][-1]}쪽 기타사항 감정도·감정서 발급"})
    trades = list(draft["tables"][0]["values"]["합계"])
    params = draft["quantity_model"]["params"]
    rate = {"table": c["base"], "row_input": None, "column_input": None,
            "trades": trades, "trade_in_columns": True,
            "row_by_trade": {trade: "합계" for trade in trades},
            "basis_cites_by_row": {"합계": cite((c["base_quote_id"], c["base_quote"]))}}
    params["unit_rate_table"] = rate
    params["quantity_input"] = c["quantity"]
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "additive_deltas"
    params["coefficient_rules"] = [{
        "kind": "area_increment", "table": c["area_table"], "row": "계수",
        "area_input": c["area"], "cite": cite(c["n_cite"]),
        **({"land_input": c["land"], "base_area_by_value": c["base_by_land"]}
           if c.get("land") else {"base_area": c["base_area"]})
    }]
    if c.get("registration_table"):
        params["coefficient_rules"].append({"table": c["registration_table"], "row": "계수",
                                              "input": c["land"], "cite": cite(c["land_cite"])})
    params["coefficient_rules"].append({"table": c["region_table"], "row": "계수",
                                         "input": c["region"], "cite": cite(c["region_cite"])})
    draft["blocked"] = [b for b in draft.get("blocked", [])
                        if b.get("blocked_if", {}).get("input") != c["appraisal_input"]]
    draft["blocked"].append({
        "condition": f"{c['appraisal_input']} == true",
        "blocked_if": {"input": c["appraisal_input"], "op": "==", "value": True},
        "reason": "추가 품을 가산할 수 있다고만 되어 있고 수치가 명시되지 않아 계산 불가",
        "source": f"PDF {c['physical'][-1]}쪽 기타사항 감정도·감정서 발급",
        "cite": [cite(c["appraisal_cite"])]
    })
    draft["quantity_model"]["steps"] = [
        f"{c['base']} 합계행에서 직종별 1필지 기본 품을 조회한다.",
        "해당 절의 기준면적과 입력 면적에서 가산횟수 n을 구해 원문 면적계수 표를 적용한다.",
        "등록지와 지역 계수를 각각 원문 표에서 찾아 적용한다.",
        "인쇄된 계산예에 따라 기본 1.00에 각 계수의 초과분(계수-1.00)을 더한 총 계수를 적용한다.",
        "기본 단위당 직종별 품에 총 계수와 필지 수를 반영한다. 감정도 발급 추가 품은 출처에 수치가 없어 차단한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, draft


def main():
    chunks = ROOT / "data/processed/chunks.all.jsonl"
    records = {}
    validations = {}
    for section, c in CONFIG.items():
        path, draft = repair(section, c)
        local_records = []
        for inputs, factor, printed in c["cases"]:
            result = per_unit(draft, inputs)
            if inputs[c["appraisal_input"]]:
                assert result.get("status") == "blocked", (section, inputs, result)
                local_records.append({"inputs": inputs, "status": result["status"]})
                continue
            assert result.get("status") == "computed", (section, inputs, result)
            expected = [Fraction(x) * factor for x in c["rates"]]
            actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
            assert actual == expected == [Fraction(x) for x in printed], (section, inputs, actual, printed)
            priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                                inputs, "2026-10-01")
            assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
            local_records.append({"inputs": inputs, "status": result["status"],
                                  "expected": [str(x) for x in expected],
                                  "offline_price_status": priced["status"],
                                  "unit_lines": result["unit_lines"]})
        records[section] = local_records
        validations[section] = validate_one(path, ROOT / "data/drafts", load_chunks(chunks), file_sha256(chunks))
        assert validations[section]["ok"], validations[section]

    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for section, validation in validations.items():
        path = ROOT / f"data/drafts/specs/토목/{section}.json"
        rel = path.relative_to(ROOT / "data/drafts").as_posix()
        old = next(x for x in report["results"] if x["path"].replace("\\", "/") == rel)
        report["ok"] += int(validation["ok"]) - int(old["ok"])
        for key in ("with_format_issues", "with_citation_issues"):
            field = key.removeprefix("with_")
            report[key] += int(bool(validation[field])) - int(bool(old[field]))
        report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for section in CONFIG:
        ident = next(json.loads(p.read_text(encoding="utf-8"))["draft"]["id"]
                     for p in (ROOT / "data/drafts/specs/토목").glob(f"{section}.json"))
        index["failed"] = [item for item in index["failed"] if item["id"] != ident]
        index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "sections": list(CONFIG), "physical_pages": {s: c["physical"] for s, c in CONFIG.items()},
        "source_images": {s: c["images"] for s, c in CONFIG.items()},
        "source_cells_checked": {"9-14-1": 12, "9-14-2": 10},
        "scenarios": records,
        "scope": "Independently compared source base rate cells, all source coefficient cells and printed example outputs. Source examples for both sections explicitly show 1.00 + 0.00 + 0.40 + 0.60 = 2.00; also tested source base threshold, a one-increment case, offline prices and blocking the unspecified appraisal addition."
    }
    out = ROOT / "evals/runtime_validation/per-unit-9-14-1-2-additive-coefficient-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sections": list(CONFIG), "focused_validation": {s: v["ok"] for s, v in validations.items()},
                      "source_cells": audit["source_cells_checked"], "scenario_count": sum(map(len, records.values()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()

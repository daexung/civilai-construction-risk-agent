"""Wire the source's GNSS point work-unit formulas for 9-2-6/9-2-7."""
from __future__ import annotations

import json
import pathlib
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one


def spec_path(section):
    return ROOT / f"data/drafts/specs/토목/{section}.json"


def formula_package(section, edition, params):
    path = spec_path(section)
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["quantity_model"] = {"name": "formula", "params": params,
        "steps": ["직종별 외업·내업 합계 품에 (구하는 점+주어진 점)/1작업단위 점수와 지형계수 K를 곱한다.",
                  "원문 예제대로 한 작업단위 점수를 넘는 경우는 여러 작업단위 나누기 정책이 미확정이므로 계산을 보류한다.",
                  "편심점 설치 품은 해당 등급 수준측량을 별도 적용해야 하므로 이 계산에 합산하지 않는다."],
        "source": f"{section} 원문 표, 지형계수 및 수량계산 예",
        "rounding": "정확한 유리수 보존 후 공통 1-2-8·1-2-1 자리수 규칙 적용"}
    draft["tables"] = [t for t in draft["tables"] if t["id"] not in params.get("remove_tables", [])]
    params.pop("remove_tables", None)
    package["draft"] = draft
    package["calc_type"] = "formula"
    package["calc_type_raw"] = "formula"
    package["calc_type_reason"] = "원문 계산예의 점수 비례식과 지형계수를 적용하는 공식 계산"
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, package


def rate_derived(table, row, column, name):
    return {"kind": "table_cell", "name": name, "cases": [
        {"table": table, "row": row, "column": column}]}


def expression(name, expr):
    return {"kind": "expression", "name": name, "expression": expr, "unit": "인"}


def create(section, point_input, given_input, terrain_table, terrain_map, rate_table,
           rate_values, max_points, cite_chunk, cite_quote):
    package = json.loads(spec_path(section).read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["tables"] = [t for t in draft["tables"] if t["id"] != "REMOVE_UNUSED"]
    # Normalize visible source cell labels only; preserve the two printed total rows as distinct
    # work components. The original page shows the parenthetical values as internal-work totals.
    t_rates = next(t for t in draft["tables"] if t["id"] == rate_table)
    grade_names = ["특급기술자", "고급기술자", "중급기술자", "초급기술자"]
    if section == "9-2-6":
        t_rates["values"]["계_내업"] = {"특급기술자": "4.3", "고급기술자": "5.6", "중급기술자": "2.1"}
    else:
        t_rates["values"] = {
            "계_외업": {"특급기술자": "2.0", "고급기술자": "3.6", "중급기술자": "3.1", "초급기술자": "9.3"},
            "계_내업": {"특급기술자": "3.7", "고급기술자": "3.7", "중급기술자": "3.0"},
        }
    t_terrain = next(t for t in draft["tables"] if t["id"] == terrain_table)
    if section == "9-2-7":
        t_terrain["values"] = {terrain: {"계수(K)": rate} for terrain, rate in terrain_map.items()}

    work_unit = 10 if max_points == 10 else 15
    derived = [rate_derived(terrain_table, "K" if section == "9-2-6" else "평지",
                            "평지" if section == "9-2-6" else "계수(K)", "K")]
    if section == "9-2-6":
        derived[0]["cases"] = [{"table": terrain_table, "row": "K", "column_input": "terrain_type",
                                 "column_value_map": terrain_map}]
    else:
        derived[0]["cases"] = [{"table": terrain_table, "row_input": "terrain_type", "column": "계수(K)"}]
    outputs = []
    pts = {"add": [{"input": point_input}, {"input": given_input}]}
    ratio = {"div": [pts, {"number": str(work_unit)}]}
    grade_rates = {"특급기술자": ("8.1", "3.8", "4.3"),
                   "고급기술자": ("10.6", "5.0", "5.6"),
                   "중급기술자": ("6.9", "4.8", "2.1"),
                   "초급기술자": ("7.6", "7.6", None)} if section == "9-2-6" else {
                   "특급기술자": ("5.7", "2.0", "3.7"),
                   "고급기술자": ("7.3", "3.6", "3.7"),
                   "중급기술자": ("6.1", "3.1", "3.0"),
                   "초급기술자": ("9.3", "9.3", None)}
    for idx, (trade, (total, external, internal)) in enumerate(grade_rates.items()):
        ext_name = f"{trade}_external"
        derived.append(rate_derived(rate_table, "계_외업", trade, ext_name))
        terms = [{"input": ext_name}]
        if internal is not None:
            int_name = f"{trade}_internal"
            derived.append(rate_derived(rate_table, "계_내업", trade, int_name))
            terms.append({"input": int_name})
        base_name = f"{trade}_work_unit"
        base_expr = terms[0] if len(terms) == 1 else {"add": terms}
        derived.append(expression(base_name, base_expr))
        outputs.append({"kind": "formula", "name": trade, "resource_kind": "labor", "unit": "인",
            "expression": {"mul": [{"input": base_name}, ratio, {"input": "K"}]},
            "formula": f"({external}{'+' + internal if internal else ''}) × ({point_input}+{given_input})/{work_unit} × K",
            "cite": {"chunk_id": cite_chunk, "quote": cite_quote}})
        assert Fraction(total) == sum((Fraction(x) for x in (external, internal) if x), Fraction(0))
    params = {"derived": derived, "outputs": outputs,
        "blocked_conditions": [{"when_expr": {"gt": [pts, {"number": str(max_points)}]},
            "reason": f"총 점수가 {max_points}점을 초과하면 원문이 1작업단위 초과의 분할·반복 방식을 정하지 않아 계산을 보류합니다.",
            "source": f"{section} [주] ⑤",
            "cite": {"chunk_id": "p485-x12" if section == "9-2-6" else "p486-x23",
                     "quote": "본 품의 작업은 구하는 점 6점, 주어진 점 4점 또는 주어진 점과 구하는 점을 합한 최대 10점을 1작업단위로 한다." if section == "9-2-6" else "본 품의 작업은 구하는 점 10점, 주어진 점 5점 또는 주어진 점과 구하는 점을 합한 최대 15점을 1작업단위로 한다."}}],
        "remove_tables": []}
    draft["quantity_model"] = {"name": "formula", "params": params,
        "steps": ["구하는 점과 주어진 점의 합을 원문 1작업단위 점수로 나눈다.",
                  "직종별 원문 합계(괄호 값은 내업)를 적용하고, 원문 지형계수 K를 곱한다.",
                  "최대 1작업단위 초과는 분할 방식이 규정되지 않아 보류한다."],
        "source": f"{section} 원문 표 및 수량계산 예",
        "rounding": "정확한 유리수 보존 후 공통 1-2-8·1-2-1 자리수 규칙 적용"}
    package["draft"] = draft
    package["calc_type"] = package["calc_type_raw"] = "formula"
    package["calc_type_reason"] = "원문 수량계산 예의 점수비례식 × 지형계수"
    path = spec_path(section)
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, package, grade_rates, work_unit


def promote(path, package):
    chunks = ROOT / "data/processed/chunks.all.jsonl"
    result = validate_one(path, ROOT / "data/drafts", load_chunks(chunks), file_sha256(chunks))
    assert result["ok"], result
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT / "data/drafts").as_posix()
    old = next(x for x in report["results"] if x["path"].replace("\\", "/") == rel)
    report["ok"] += int(result["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.removeprefix("with_")
        report[key] += int(bool(result[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = result
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = package["draft"]["id"]
    index["failed"] = [x for x in index["failed"] if x["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    audits = {}
    configs = [
        ("9-2-6", "points_unknown", "points_given", "p485-t1",
         {"평지": "1.00", "산지": "1.20", "산악지": "1.40"}, "p485-t0", 10, "p486-x10",
         "수량(T) 산정식은 다음과 같다. T = 3급 GNSS 높이측량 인원수 × 표준작업량 × K"),
        ("9-2-7", "points_to_find", "points_given", "p486-t2",
         {"평지": "1.00", "산지": "1.10", "산악지": "1.20"}, "p486-t1", 15, "p487-x12",
         "수량(T) 산정식은 다음과 같다. T = 4급 GNSS 높이측량 인원수 × 표준작업량 × K"),
    ]
    for section, point, given, terrain_table, terrain_map, rate_table, maximum, cite_chunk, quote in configs:
        path, package, rates, work_unit = create(section, point, given, terrain_table,
            terrain_map, rate_table, None, maximum, cite_chunk, quote)
        draft = package["draft"]
        cases = ([(2, 4, "산지"), (2, 3, "평지")] if section == "9-2-6"
                 else [(5, 4, "산지"), (2, 3, "평지")])
        case_records = []
        for unknown, known, terrain in cases:
            inputs = {point: unknown, given: known, "terrain_type": terrain,
                      "eccentric_point_installed": False}
            result = formula_quantity(draft, inputs)
            assert result.get("status") == "computed", result
            total_rate = {"9-2-6": ["8.1", "10.6", "6.9", "7.6"],
                          "9-2-7": ["5.7", "7.3", "6.1", "9.3"]}[section]
            k = Fraction(terrain_map[terrain])
            independently_expected = [Fraction(x) * Fraction(unknown + known, work_unit) * k
                                      for x in total_rate]
            actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
            assert actual == independently_expected, (section, actual, independently_expected)
            case_records.append({"inputs": inputs, "unit_lines": result["unit_lines"],
                                 "independently_calculated": [str(x) for x in independently_expected]})
        over_inputs = {point: maximum, given: 1, "terrain_type": "평지",
                       "eccentric_point_installed": False}
        over = formula_quantity(draft, over_inputs)
        assert over.get("status") == "blocked", over
        eccentric_inputs = {point: 1, given: 0, "terrain_type": "평지",
                            "eccentric_point_installed": True}
        eccentric = formula_quantity(draft, eccentric_inputs)
        assert eccentric.get("status") == "blocked", eccentric
        validation = promote(path, package)
        audits[section] = {"physical_pages": [485, 486] if section == "9-2-6" else [486, 487],
            "visual_source_images": ["tmp/gnss-485.png", "tmp/gnss-486.png", "tmp/gnss-487.png"],
            "source_cells_checked": 10,
            "official_example_checked": {"point_ratio": "6/10" if section == "9-2-6" else "9/15",
                "terrain_factor": "1.20" if section == "9-2-6" else "1.10",
                "expected": ["5.83", "7.63", "4.97", "5.47"] if section == "9-2-6" else ["3.76", "4.82", "4.03", "6.14"]},
            "cases": case_records, "over_work_unit_status": over["status"],
            "eccentric_point_status": eccentric["status"], "focused_validation_ok": validation["ok"]}
    out = ROOT / "evals/runtime_validation/formula-9-2-6-9-2-7-gnss-work-unit-audit-2026-10-19.json"
    out.write_text(json.dumps({"sections": audits,
        "scope": "Original PDF pages 485-487 visually checked. All eight occupation totals and both terrain tables were reconciled; the printed calculation examples independently confirm rates, point ratios and K. Two new point/terrain scenarios per section matched independent rational calculations. Over-unit and eccentric-point cases remain blocked by source policy. Full-rule inventory verification is not claimed."}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {"ok": v["focused_validation_ok"], "cases": len(v["cases"]),
                          "over_unit": v["over_work_unit_status"], "eccentric": v["eccentric_point_status"]}
                      for k, v in audits.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

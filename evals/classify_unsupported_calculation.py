"""미지원(calculator_selection) 명세를 표 구조·입력·단계의 실측으로 분류한다. 외부 호출 없음.

분류는 초안의 calc_type_reason 문장이 아니라 명세에 실제 담긴 표·입력·단계의 구조로 판정한다. 문장은 근거 후보로만 적는다.
원문 PDF 대조 여부는 항목마다 `pdf_verified`로 따로 기록한다(이 스크립트는 대조하지 않으므로 항상 False).
산출: data/drafts/unsupported_classification.json, docs/reviews/calculation-unsupported-classification-2026-10-19.md
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "data/drafts/specs"
EXECUTABLE = ROOT / "data/drafts/executable.json"
OUT = ROOT / "data/drafts/unsupported_classification.json"
DOC = ROOT / "docs/reviews/calculation-unsupported-classification-2026-10-19.md"

MACHINE_CODE = re.compile(r"\b\d{4}-?\d{0,4}\b")

CATEGORIES = {
    "G1_sub_task_quantity_units": "작업 종류마다 물량 단위가 달라 상담 계층의 단일 물량 필드로 표현되지 않음(공통 기능 부족)",
    "G2_work_time_formula_chain": "지층·규격별 작업소요시간(T=Σ…)을 구한 뒤 인·일/대·일로 환산하는 식 사슬(공식 계산기+표 항 확장 필요)",
    "G3_hourly_capacity_formula": "장비 시간당 작업량(Q) 산정식과 계수표(인·일을 직접 내지 않음)",
    "G4_survey_coefficient_formula": "측량 품: 인원×작업량×지형·면적·지역 계수 등 여러 표를 곱·합하는 식",
    "G5_parse_loss_or_price_lists": "표가 비었거나 행·열 이름이 병합/누락되어 원문 재추출이 먼저 필요하거나, 기계 가격·계수 목록",
    "G6_policy_or_explanatory": "계산 대상이 아닌 기준·설명·참조 항목(역할과 참조 관계를 보존)",
    "G7_source_leaves_rule_open": "원문이 적용 범위·율을 '범위 내'로만 두어 검토자가 승인한 시스템 정책이 필요",
    "R_remaining_daily_or_per_unit": "표와 입력이 있어 기존 일당 작업조/단위당 품으로 연결 가능해 보이나 아직 원문 대조·연결하지 않음",
}


def table_defects(table: dict, vocabulary: set[str]) -> list[str]:
    defects = []
    values = table.get("values") or {}
    if not values:
        return ["empty_values"]
    for row, cells in values.items():
        joined = [v for v in vocabulary if v in str(row)]
        if "\n" in str(row) or len(MACHINE_CODE.findall(str(row))) > 1 or len(joined) > 1:
            defects.append(f"merged_row_label:{str(row)[:30]}")
        if not isinstance(cells, dict) or not cells:
            defects.append(f"empty_row:{str(row)[:20]}")
            continue
        for column, value in cells.items():
            if "\n" in str(column):
                defects.append(f"newline_column:{str(column)[:20]}")
            if str(value).strip() in ("", "-", "None"):
                defects.append(f"blank_cell:{str(row)[:15]}/{str(column)[:15]}")
    return sorted(set(defects))[:8]


def trade_vocabulary() -> set[str]:
    names: set[str] = set()
    for path in SPECS.rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["calc_type"] not in ("daily_crew", "per_unit"):
            continue
        crew = package["draft"]["quantity_model"].get("params", {}).get("crew")
        if isinstance(crew, dict):
            names.update(crew.get("trades") or [])
    return {name for name in names if 1 < len(name) < 12}


def categorize(spec: dict, package: dict, defects: dict) -> tuple[str, list[str]]:
    """구조 사실만으로 분류하고, 어떤 사실로 그렇게 봤는지 함께 돌려준다."""
    section, division = spec["section_no"], spec["division"]
    text = " ".join(spec["quantity_model"].get("steps", [])) + " " + (package.get("calc_type_reason") or "")
    facts = []
    units = {field.get("unit") for field in spec["inputs"] if field["name"] == "quantity" or "quantity" in field["name"]}
    if division == "토목" and re.match(r"9-\d+-\d+", section):
        return "G4_survey_coefficient_formula", [f"토목 {section}: 측량 절", f"표 {len(spec['tables'])}개, 입력 {len(spec['inputs'])}개"]
    if division == "공통" and re.match(r"8-2-\d+", section):
        return "G3_hourly_capacity_formula", [f"공통 {section}: 건설기계 시간당 작업량 절", "단계 문구에 Q/시간당" if re.search(r"시간당|Q\s*=", text) else "표·계수 중심"]
    if division == "공통" and re.match(r"(8-[1345]-\d+|\d{4}-\d{4}|5203-|5205-|7811-|2208-|3302-)", section):
        facts.append("기계 분류번호/가격/경비 목록 절" if re.match(r"(8-[45]|\d{4}-)", section) else "건설기계 일반 기준 절")
        if not spec["tables"] or any(defects.values()):
            return "G5_parse_loss_or_price_lists", facts + [f"표 결함 {sum(len(v) for v in defects.values())}건/표 없음" ]
        return "G6_policy_or_explanatory", facts
    if re.search(r"작업소요시간|시공시간|\bT\s*=|Σ|∑", text) and spec["tables"]:
        return "G2_work_time_formula_chain", ["단계에 작업소요시간/T 합산식", f"표 {len(spec['tables'])}개"]
    if not spec["tables"] and not spec["inputs"]:
        if re.search(r"누락|표가 없|제공되지", text):
            return "G5_parse_loss_or_price_lists", ["표·입력 없음", "초안 사유에 표 누락 언급"]
        return "G6_policy_or_explanatory", ["표·입력 없음"]
    if any(defects.values()):
        return "G5_parse_loss_or_price_lists", [f"표 결함: {next(iter(d for d in defects.values() if d))[:2]}"]
    if len({u for u in units if u}) > 1 or any("/" in str(u) and u.count("/") >= 2 for u in units if u):
        return "G1_sub_task_quantity_units", [f"물량 단위 {sorted(u for u in units if u)}"]
    if re.search(r"범위\s*내|까지\s*감|까지\s*가산|임의", text):
        return "G7_source_leaves_rule_open", ["단계/사유에 '범위 내·까지' 문구"]
    if re.search(r"일반적인 기준|설명|판단하기 위한|정책", text) and not spec["inputs"]:
        return "G6_policy_or_explanatory", ["입력 없음"]
    return "R_remaining_daily_or_per_unit", [f"표 {len(spec['tables'])}개 결함 없음, 입력 {len(spec['inputs'])}개"]


def main() -> int:
    skipped = {x["id"]: x for x in json.loads(EXECUTABLE.read_text(encoding="utf-8"))["skipped"]
               if x["stage"] == "calculator_selection"}
    vocabulary = trade_vocabulary()
    rows = []
    for path in sorted(SPECS.rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        if spec["id"] not in skipped:
            continue
        defects = {t["id"]: table_defects(t, vocabulary) for t in spec["tables"]}
        category, facts = categorize(spec, package, defects)
        rows.append({
            "id": spec["id"], "path": str(path.relative_to(ROOT)).replace("\\", "/"), "title": spec["title"],
            "source_pages": spec.get("source_pages"), "draft_calc_type": package["calc_type"],
            "category": category, "category_basis": facts, "pdf_verified": False,
            "tables": [t["id"] for t in spec["tables"]], "inputs": [i["name"] for i in spec["inputs"]],
            "table_defects": {k: v for k, v in defects.items() if v},
            "draft_reason": package.get("calc_type_reason"), "steps": spec["quantity_model"].get("steps", []),
        })
    OUT.write_text(json.dumps({"count": len(rows), "categories": CATEGORIES, "items": rows}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    counts = Counter(row["category"] for row in rows)
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row["id"].split("/", 1)[1])
    lines = ["# 미지원 명세 분류 (2026-10-19)", "",
             f"대상: `executable.json`에서 계산기 선택 단계에서 건너뛴 {len(rows)}건. 분류는 명세의 표·입력·단계 구조로 했고 "
             "원문 PDF 대조는 하지 않았다(`pdf_verified=false`). 연결된 절은 같은 날 `docs/handoffs/CALCULATION-AUTOMATION-RESUME.md`에 있다.", ""]
    for key, label in CATEGORIES.items():
        lines += [f"## {key} — {counts.get(key, 0)}건", label, ""]
        lines += [f"- {item}" for item in sorted(by_category.get(key, []))]
        lines.append("")
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(len(rows), dict(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())

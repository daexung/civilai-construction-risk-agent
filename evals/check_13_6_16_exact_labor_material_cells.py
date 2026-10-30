"""Independent original-table and per-ton labor/material calculation audit."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-6-16.json").read_text(encoding="utf-8"))["draft"]
LABOR = {
    "기술관리": {"기계기사": "1.66"},
    "운반검측": {"플랜트기계설치공": "0.05", "특별인부": "0.05"},
    "수정": {"산소절단공": "0.05", "플랜트기계설치공": "0.05", "특별인부": "0.10"},
    "설치준비철근정리": {"산소절단공": "0.047", "특별인부": "0.047"},
    "Chipping": {"석공": "0.1", "특별인부": "0.05"},
    "Beam 설치": {"특별인부": "0.175"}, "Crane 작업": {"특수비계공": "0.18"},
    "Beam 설치 crane 작업": {"측량사": "0.14"},
    "1차 센터링": {"측량조수": "0.14", "특수비계공": "0.14", "특별인부": "0.28", "플랜트기계설치공": "0.14"},
    "턴버클 용접": {"플랜트용접공": "0.21", "특별인부": "0.21"},
    "Beam 완전 고정": {"산소절단공": "0.015", "플랜트용접공": "2.7", "특별인부": "2.7"},
    "Trash Rack 설치": {"특별인부": "0.67"},
    "1차 조립": {"특수비계공": "0.59", "플랜트기계설치공": "0.45"},
    "2차 센터링": {"측량사": "0.087", "측량조수": "0.087", "플랜트기계설치공": "0.087", "특별인부": "0.166", "플랜트용접공": "0.79"},
    "검사": {"플랜트기계설치공": "0.035", "특별인부": "0.035"},
    "도장준비": {"플랜트제관공": "2.98"}, "도장": {"도장공": "2.98"},
    "강재거푸집철거": {"플랜트용접공": "0.017", "특별인부": "0.017"},
    "뒷정리": {"플랜트기계설치공": "0.035", "산소절단공": "0.017", "특별인부": "0.35"},
    "전원조작": {"플랜트전공": "0.52", "특별인부": "0.52"},
}
MATERIALS = {"수정·절단": {"산소": "0.029"},
             "용접": {"아세틸렌": "0.012", "용접봉": "5.95"},
             "도장": {"Tar Epoxy": "7.06", "시너": "1.58"}}
MATERIAL_UNIT = {"산소": ("병", "병/ton"), "아세틸렌": ("병", "병/ton"),
                 "용접봉": ("kg", "kg/ton"), "Tar Epoxy": ("ℓ", "ℓ/ton"),
                 "시너": ("ℓ", "ℓ/ton")}
GAS_QUOTE = "※ 산소량 규격은 대기압상태를 기준하며, 단위 ‘병’은 35℃에서 150기압으로 압축용기에 넣어 사용하는 것을 기준한다."

def main():
    tables = {t["id"]: t for t in SPEC["tables"]}
    labor_expected = {"p876-t2": dict(list(LABOR.items())[:8]),
                      "p877-t0": dict(list(LABOR.items())[8:])}
    for tid, rows in labor_expected.items():
        assert tables[tid]["values"] == rows, (tid, tables[tid]["values"], rows)
    assert tables["p877-t1"]["values"] == MATERIALS
    labor_cells = [(tid, row, trade, Fraction(raw)) for tid, rows in labor_expected.items()
                   for row, cells in rows.items() for trade, raw in cells.items()]
    material_cells = [(row, name, raw) for row, cells in MATERIALS.items() for name, raw in cells.items()]
    result = per_unit(SPEC, {"quantity": "2"}, labor_only=True)
    assert result["status"] == "computed" and len(result["unit_lines"]) == 46, result
    labor_lines = [x for x in result["unit_lines"] if x["kind"] == "labor"]
    material_lines = [x for x in result["unit_lines"] if x["kind"] == "material"]
    assert len(labor_cells) == len(labor_lines) == 41
    assert len(material_cells) == len(material_lines) == 5
    expected_labor_total = sum((x[3] for x in labor_cells), Fraction(0)) * 2
    actual_labor_total = Fraction(0)
    for tid, row, trade, value in labor_cells:
        matches = [x for x in labor_lines if x["name"] == trade and x["citations"][0]["row"] == row]
        assert len(matches) == 1, (tid, row, trade, matches)
        line = matches[0]
        cite = line["citations"][0]
        assert (cite["internal_id"], cite["column"], Fraction(cite["value"])) == (tid, trade, value)
        assert line["unit"] == "인/ton" and Fraction(line["exact"]) == value
        actual_labor_total += Fraction(line["exact"]) * 2
    assert expected_labor_total == actual_labor_total
    for row, name, raw in material_cells:
        matches = [x for x in material_lines if x["name"] == name]
        assert len(matches) == 1, (row, name, matches)
        line = matches[0]
        cite = line["citations"][0]
        assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
            "p877-t1", row, name, raw)
        assert line["unit"] == MATERIAL_UNIT[name][1]
        assert Fraction(line["exact"]) == Fraction(raw)
        if name in ("산소", "아세틸렌"):
            assert any(c.get("internal_id") == "p877-x34" and c.get("quote") == GAS_QUOTE
                       for c in line["citations"]), (name, line["citations"])
    price = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"),
                       {"quantity": "2"}, "2026-10-19")
    assert price["status"] == "PARTIAL" and len(price["lines"]) == 46
    report = {
        "status": "passed", "source_pdf_pages": [876, 877], "printed_pages": [820, 821],
        "labor_source_cells_independently_compared": len(labor_cells),
        "material_source_cells_independently_compared": len(material_cells),
        "source_process_rows": {"labor": sum(map(len, labor_expected.values())),
                                "material": len(MATERIALS)},
        "labor_person_days_per_ton": str(sum((x[3] for x in labor_cells), Fraction(0))),
        "two_ton_labor_person_days": str(expected_labor_total),
        "material_unit_rates": {name: f"{value}{MATERIAL_UNIT[name][0]}/ton"
                                for row, name, value in material_cells},
        "gas_container_rule_quote_checked": GAS_QUOTE,
        "offline_price_status": price["status"], "full_rule_verification": False,
    }
    (ROOT / "evals/runtime_validation/13-6-16-exact-labor-material-source-audit-2026-10-19.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

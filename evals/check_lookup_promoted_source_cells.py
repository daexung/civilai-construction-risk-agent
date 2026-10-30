"""Compare every cell in five lookup candidates with PDF page content and locators."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def spec(division: str, section: str) -> dict:
    return json.loads((ROOT / "data/drafts/specs" / division / f"{section}.json").read_text(
        encoding="utf-8"))["draft"]


def check_spec_table(package: dict, table_id: str, expected: dict,
                     input_names: tuple[str, str], printed_pages: dict[int, int],
                     machine_on_row: bool = False) -> int:
    table = next(t for t in package["tables"] if t["id"] == table_id)
    observed = {}
    checks = 0
    for row, columns in table["values"].items():
        for column, value in columns.items():
            cell_key = (column, row) if machine_on_row else (row, column)
            assert cell_key in expected, (table_id, cell_key, "not present in independent PDF table reading")
            assert str(value) == str(expected[cell_key]), (table_id, cell_key, value, expected[cell_key])
            user_inputs = ({input_names[0]: row, input_names[1]: column} if machine_on_row
                           else {input_names[0]: column, input_names[1]: row})
            result = lookup(package, user_inputs)
            assert result["status"] == "computed", (table_id, cell_key, result)
            assert str(result["value"]) == str(expected[cell_key]), (table_id, cell_key, result)
            assert result.get("unit") == table.get("unit"), (table_id, cell_key, table.get("unit"), result)
            citation = result["provenance"]["citations"][0]
            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"],
                    citation["pdf_page"], citation["printed_page"]) == (
                        table_id, row, column, str(expected[cell_key]), int(table_id[1:table_id.index("-")]),
                        printed_pages[int(table_id[1:table_id.index("-")])]), (table_id, cell_key, citation)
            observed[cell_key] = str(value)
            checks += 1
    assert observed.keys() == expected.keys(), (table_id, sorted(expected.keys() - observed.keys()))
    return checks


def check_lookup_cells(package: dict, table_id: str, expected: dict,
                       input_names: tuple[str, str], pdf_page: int,
                       printed_page: int) -> int:
    table = next(t for t in package["tables"] if t["id"] == table_id)
    declared = {(row, column): str(value) for row, columns in table["values"].items()
                for column, value in columns.items()}
    assert declared == expected, (table_id, "declared matrix differs from PDF transcription",
                                  declared, expected)
    observed = {}
    for (row, column), value in expected.items():
        result = lookup(package, {input_names[0]: row, input_names[1]: column})
        assert result["status"] == "computed", (table_id, row, column, result)
        assert str(result["value"]) == value, (table_id, row, column, value, result)
        assert result.get("unit") == table.get("unit"), (table_id, table.get("unit"), result)
        citation = result["provenance"]["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"],
                citation["pdf_page"], citation["printed_page"]) == (
                    table_id, row, column, value, pdf_page, printed_page), (row, column, citation)
        observed[(row, column)] = value
    assert set(observed) == set(expected)
    return len(observed)


def main() -> int:
    machine_prefixes = {
        "2101": "크레인 (무한궤도)", "2104": "크레인 (타이어)", "2105": "트럭탑재형 크레인",
        "2106": "고소작업차", "2107": "터널용고소작업차", "2115": "리더(고정형)",
        "2116": "리더(회전형)", "2117": "케이싱", "2118": "스킵버킷", "2208": "타워크레인",
        "2210": "건설용리프트 (인화물용)", "2330": "디젤기관차", "2402": "경운기",
        "2502": "지게차", "2602": "트랙터 (타이어)", "2702": "트럭트랙터 및 평판트레일러",
        "3108": "아스팔트믹싱 플랜트", "3201": "아스팔트피니셔", "3302": "아스팔트 디스트리뷰터",
        "3430": "아스팔트 스프레이어", "3450": "현장가열표층재생기", "3530": "스테이빌라이저 (안정기)",
        "3601": "콘크리트피니셔 (포장용)", "3611": "콘크리트피니셔 (중앙분리대용)",
        "3701": "콘크리트스프레더", "3801": "콘크리트조면 마무리기",
        "3805": "콘크리트롤러페이버", "3901": "슬러리실기계",
    }
    printed = {347: 291, 348: 292, 349: 293}
    p853 = spec("공통", "8-5-3")
    p854 = spec("공통", "8-5-4")
    count = 0
    for table_id, package, pages in (("p347-t0", p853, [347]), ("p348-t0", p853, [348]),
                                     ("p349-t0", p854, [349])):
        table = next(t for t in package["tables"] if t["id"] == table_id)
        pages_data = _machine_page_cells(pages, machine_prefixes)
        actual = {(code, machine): value for code, machine, value in pages_data}
        expected_by_source = {}
        for row, cols in table["values"].items():
            for machine, value in cols.items():
                key = (machine, row) if table_id == "p349-t0" else (row, machine)
                expected_by_source[key] = str(value)
        assert set(actual) == set(expected_by_source), (table_id, set(expected_by_source)-set(actual),
                                                        set(actual)-set(expected_by_source))
        assert actual == expected_by_source, (table_id, [(key, expected_by_source[key], actual.get(key))
                                                         for key in expected_by_source if actual.get(key) != expected_by_source[key]])
        count += check_spec_table(package, table_id, expected_by_source,
                                  ("machine_type", "classification_number"), printed,
                                  machine_on_row=table_id == "p349-t0")

    # The next two tables have small enough source matrices to transcribe directly from the rendered PDF.
    p322 = spec("토목", "3-2-2")
    t322 = next(t for t in p322["tables"] if t["id"] == "p395-t1")
    expected322 = {
        ("소형브레이커( 1 . 3 ㎥/ m i n )", "풍화암"): "0.38",
        ("대형브레이커 +굴착기0.7㎥", "풍화암"): "5.6∼6.8",
        ("대형브레이커 +굴착기0.7㎥", "연암"): "4.5∼5.5",
        ("대형브레이커 +굴착기0.7㎥", "보통암"): "3.1∼3.7",
        ("대형브레이커 +굴착기0.7㎥", "경암"): "2.3∼2.9",
    }
    assert t322["values"] == {r: {c: v for (rr, c), v in expected322.items() if rr == r}
                               for r in t322["values"]}, t322["values"]
    count += check_lookup_cells(p322, "p395-t1", expected322, ("equipment", "rock_type"), 395, 339)

    p744 = spec("토목", "7-4-4")
    expected744 = {
        ("보통토사 | 선종 펌프준설선", "시공수심별 여굴 두께 5.5m"): "0.6m",
        ("보통토사 | 선종 펌프준설선", "시공수심별 여굴 두께 5.5∼9.0m 미만"): "0.7m",
        ("보통토사 | 선종 펌프준설선", "시공수심별 여굴 두께 9.0m 이상"): "1.0m",
        ("보통토사 | 선종 그래브준설선", "시공수심별 여굴 두께 5.5∼9.0m 미만"): "0.5m",
        ("보통토사 | 선종 그래브준설선", "시공수심별 여굴 두께 9.0m 이상"): "0.6m",
        ("암반 | 선종 그래브준설선", "시공수심별 여굴 두께 5.5m"): "0.5m",
        ("암반 | 선종 그래브준설선", "시공수심별 여굴 두께 5.5∼9.0m 미만"): "0.5m",
        ("암반 | 선종 그래브준설선", "시공수심별 여굴 두께 9.0m 이상"): "0.5m",
    }
    count += check_lookup_cells(p744, "p451-t2", expected744, ("soil_and_dredger", "water_depth"), 451, 395)
    blank = lookup(p744, {"soil_and_dredger": "보통토사 | 선종 그래브준설선",
                          "water_depth": "시공수심별 여굴 두께 5.5m"})
    assert blank["status"] == "unresolvable", blank
    assert count == 114, count
    print("PASS four PDF lookup specs: all 114 cells, table axes, units and citations; source blank remains unresolved")
    return 0


def _machine_page_cells(page_numbers: list[int], type_by_prefix: dict[str, str]) -> list[tuple[str, str, str]]:
    """Extract code/price pairs by PDF word coordinates; machine groups map from visible table labels."""
    doc = pymupdf.open(PDF)
    result = []
    for number in page_numbers:
        page = doc[number - 1]
        lines = defaultdict(list)
        for word in page.get_text("words"):
            x0, y0, _x1, _y1, text, *_ = word
            if 80 <= y0 <= page.rect.height - 70 and 300 <= x0 < 570:
                lines[round(y0 / 3) * 3].append((x0, text))
        prefix = None
        for _, words in sorted(lines.items()):
            codes = [text for x, text in words if 300 <= x < 480 and re.fullmatch(r"(?:\d{4}-)?\d{4}", text)]
            prices = [text for x, text in words if 480 <= x < 570 and re.fullmatch(r"\d{1,3}(?:,\d{3})+", text)]
            if len(codes) != 1 or len(prices) != 1:
                continue
            code = codes[0]
            if "-" in code:
                prefix, _suffix = code.split("-", 1)
                row = code
            else:
                row = code
            assert prefix in type_by_prefix, (number, code, prefix)
            result.append((row, type_by_prefix[prefix], prices[0]))
    return result


if __name__ == "__main__":
    raise SystemExit(main())

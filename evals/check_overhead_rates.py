"""Check hand-authored overhead rates against original workbook XML cells."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "office_rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
RATES_PATH = ROOT / "data/rates/overhead_rates.json"
FORMULA_BASES = {
    "산재보험료": "노",
    "건강보험료": "직노",
    "노인장기요양보험료": "건강보험료",
    "연금보험료": "직노",
    "퇴직공제부금비": "직노",
}
FORMULA_TEXT = re.compile(r"^\(([^)]+)\)\s*[x×]\s*(\d+(?:\.\d+)?)$")


def _column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character.upper()) - ord("A") + 1
    return value


def _split_cell(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", reference.upper())
    if not match:
        raise ValueError(f"잘못된 셀 주소: {reference}")
    return _column_number(match.group(1)), int(match.group(2))


def _top_left(reference: str, merge_ranges: list[str]) -> str:
    column, row = _split_cell(reference)
    for merge_range in merge_ranges:
        start, end = merge_range.split(":")
        start_column, start_row = _split_cell(start)
        end_column, end_row = _split_cell(end)
        if start_column <= column <= end_column and start_row <= row <= end_row:
            return start.replace("$", "")
    return reference.replace("$", "")


def _workbook_cells(path: Path) -> tuple[dict[str, str], list[str]]:
    with ZipFile(path) as workbook:
        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        relationships = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheet = workbook_root.find("main:sheets/main:sheet", NS)
        if sheet is None:
            raise ValueError(f"워크북 시트 없음: {path}")
        target = targets[sheet.attrib[f"{{{NS['office_rel']}}}id"]].lstrip("/")
        sheet_path = target if target.startswith("xl/") else f"xl/{target}"

        shared_strings = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(text.text or "" for text in item.findall(".//main:t", NS))
                for item in shared_root
            ]

        sheet_root = ET.fromstring(workbook.read(sheet_path))
        cells: dict[str, str] = {}
        for cell in sheet_root.findall(".//main:c", NS):
            value = cell.find("main:v", NS)
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                content = "".join(text.text or "" for text in cell.findall(".//main:t", NS))
            elif value is None:
                continue
            elif cell_type == "s":
                content = shared_strings[int(value.text or "0")]
            else:
                content = value.text or ""
            if content.strip():
                cells[cell.attrib["r"].replace("$", "")] = content.strip()
        merges = [item.attrib["ref"] for item in sheet_root.findall(".//main:mergeCell", NS)]
        return cells, merges


def _walk_rate_items(value, source_file: str):
    if isinstance(value, dict):
        if "cell" in value and "rate" in value:
            yield source_file, value
        for key, child in value.items():
            if key == "source_file":
                continue
            yield from _walk_rate_items(child, source_file)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rate_items(child, source_file)


def main() -> int:
    data = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    sources: dict[str, tuple[dict[str, str], list[str]]] = {}
    checked = 0
    failures = []

    groups = []
    for version in data["versions"].values():
        groups.extend(group for group in version.values() if isinstance(group, dict) and "source_file" in group)
    groups.extend(group for group in data["shared_law_rates"].values())

    for version_id, version in data["versions"].items():
        for work in ("civil", "architecture"):
            group = version[work]
            formulas = group["formula_rates"]
            names = [item["name"] for item in formulas]
            if len(formulas) != len(FORMULA_BASES) or set(names) != set(FORMULA_BASES):
                failures.append(f"{version_id} {work}: 보험료·퇴직공제 항목 이름 누락 또는 중복")
            for item in formulas:
                source_text = item.get("source_text", "")
                match = FORMULA_TEXT.fullmatch(source_text)
                if not match or match.group(1) != FORMULA_BASES.get(item["name"]):
                    failures.append(f"{version_id} {work} {item['name']}: 괄호 기준 불일치 ({source_text!r})")
                elif Decimal(match.group(2)) != Decimal(item["rate"]):
                    failures.append(f"{version_id} {work} {item['name']}: 원문 요율 불일치 ({source_text!r})")

    for group in groups:
        source_file = group["source_file"]
        for filename, item in _walk_rate_items(group, source_file):
            if filename not in sources:
                source_path = ROOT / filename
                if not source_path.is_file():
                    failures.append(f"원본 파일 없음: {filename}")
                    continue
                sources[filename] = _workbook_cells(source_path)
            cells, merges = sources[filename]
            declared_cell = item["cell"]
            # An explicit value at the declared coordinate takes precedence;
            # only blank merged followers resolve to their range's top-left.
            resolved_cell = declared_cell if declared_cell in cells else _top_left(declared_cell, merges)
            actual = cells.get(resolved_cell)
            expected_text = item.get("source_text")
            if actual is None:
                failures.append(f"{filename} {declared_cell}: 셀 값 없음")
                continue
            if expected_text is not None:
                matched = actual == expected_text
            else:
                try:
                    actual_rate = Decimal(actual.strip("()"))
                    expected_rate = Decimal(str(item["rate"]))
                    matched = abs(actual_rate - expected_rate) <= Decimal("0.00000000001")
                except InvalidOperation:
                    matched = False
            checked += 1
            if not matched:
                failures.append(
                    f"{filename} {declared_cell} (실제 {resolved_cell}): "
                    f"원본={actual!r}, 명세={expected_text or item['rate']!r}"
                )

    expected_sources = {
        version[source_kind]["source_file"]
        for version in data["versions"].values()
        for source_kind in ("civil", "architecture")
    }
    if len(expected_sources) != 4:
        failures.append(f"대조 대상 워크북은 4개여야 합니다: {len(expected_sources)}")
    if not checked:
        failures.append("대조한 요율 셀이 없습니다")

    for filename in sorted(expected_sources):
        count = sum(1 for source, _ in _walk_rate_items(
            next(group for group in groups if group["source_file"] == filename), filename
        ))
        print(f"{'PASS' if filename in sources else 'FAIL'} {filename}: {count}개 rate 항목")
    for failure in failures:
        print(f"FAIL {failure}")
    print(f"{'PASS' if not failures else 'FAIL'} 원본 셀 대조 {checked}개")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

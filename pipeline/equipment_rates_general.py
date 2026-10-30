"""2026년 건설기계 경비산출표(회전된 쪽)를 열 단위로 읽어 기계별 손료·연료·운전원을 만든다.

각 기계는 한 열이며 행(필드)은 y 위치로 구분한다: 조장 53, 조수 99, 조종원 144, 잡재료(%) 187, 주연료 232,
시간당 손료 278, 건설기계가격 340, 규격 558, 분류번호 603. 값은 같은 열(x)에서 읽는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/equipment_rates/2026_machine_cost_table.pdf"
BANDS = {"foreman": 53, "assistant": 99, "operator": 144, "misc": 187, "fuel": 232,
         "depr": 278, "price": 340, "spec": 558, "code": 603}
CODE = re.compile(r"^\d{4}-\d{4}$")


def _field(y0: float) -> str | None:
    return next((name for name, y in BANDS.items() if abs(y0 - y) <= 6), None)


def parse_pages(pages: range) -> dict[str, dict]:
    machines: dict[str, dict] = {}
    with pymupdf.open(PDF) as doc:
        for number in pages:
            page = doc[number - 1]
            words = page.get_text("words")
            for code_word in (w for w in words if CODE.match(w[4]) and _field(w[1]) == "code"):
                cells: dict[str, list[str]] = {}
                for w in words:
                    field = _field(w[1])
                    if field and abs(w[0] - code_word[0]) < 4:
                        cells.setdefault(field, []).append(w[4])
                one = lambda key: cells[key][0] if len(cells.get(key, [])) == 1 else None
                machines[code_word[4]] = {"pdf_page": number, "spec": one("spec"),
                                          "price": one("price"), "depr": one("depr"), "fuel": one("fuel"),
                                          "misc": one("misc"), "operator": one("operator"),
                                          "assistant": one("assistant"), "foreman": one("foreman")}
    return machines


if __name__ == "__main__":
    found = parse_pages(range(4, 12))
    bad = {c: m for c, m in found.items() if None in (m["spec"], m["price"], m["depr"], m["operator"])}
    print(len(found), "machines;", len(bad), "incomplete")
    for code in ("0201-0070", "0201-0080", "0301-0057", "0302-0057", "0302-0095"):
        print(code, found.get(code))
    import collections
    print(collections.Counter(c[:4] for c in found))


# 견적에 연결한 기종만 JSON에 싣는다(필드 대조가 끝난 열). 접두 4자리 → (기종명, 절 번호)
REGISTERED = {"0201": "굴착기(무한궤도)", "0301": "로더(무한궤도)", "0302": "로더(타이어)"}


def merge_into_rates() -> int:
    import json
    from decimal import Decimal, ROUND_DOWN
    path = ROOT / "data/rates/equipment_rates.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for code, m in parse_pages(range(4, 12)).items():
        name = REGISTERED.get(code[:4])
        if not name:
            continue
        assert None not in (m["spec"], m["price"], m["depr"], m["fuel"], m["misc"], m["operator"]), (code, m)
        dash = lambda v: None if v == "-" else int(v)
        data["machines"][code] = {
            "name": name, "section_no": code[:4], "spec": m["spec"],
            "price_thousand_won": int(m["price"].replace(",", "")),
            "hourly_depreciation": int(m["depr"].replace(",", "")), "fuel_type": "경유",
            "fuel_l_per_hr": m["fuel"], "misc_pct_of_fuel": int(m["misc"]),
            "operator_per_day": int(m["operator"]), "assistant_per_day": dash(m["assistant"]),
            "foreman_per_day": dash(m["foreman"]), "pdf_page": m["pdf_page"]}
        count += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return count

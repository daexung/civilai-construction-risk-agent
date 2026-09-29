"""계산 결과를 표(원가계산서·내역서·일위대가·단가대비표)로 바꾸고 엑셀로 만든다.

화면과 엑셀이 같은 표를 쓰도록 응답 dict에서 한 번만 만든다.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DISCLAIMER = "표준품셈 기준 금액, 검토 전 참고용"
_RANK = {"재료비": 0, "노무비": 1, "경비": 2}
_SUBTOTALS = ("노무비 계", "경비 계")


def _num(value) -> int | float | None:
    if value is None or value == "":
        return None
    number = Decimal(str(value))
    return int(number) if number == number.to_integral_value() else float(number)


def _basis_text(line: dict) -> str:
    base, rate = line.get("base") or "", line.get("rate")
    if rate is not None and line.get("status") == "산정":
        return f"{base} {line['base_amount']:,}원 × {rate}%"
    return base


def statement_rows(statement: dict | None) -> list[dict]:
    """비목별로 묶어 재료비 → 노무비 → 경비 → 순공사원가 … 도급액 순으로 늘어놓는다."""
    if not statement:
        return []
    indexed = list(enumerate(statement.get("lines", [])))

    def key(item: tuple[int, dict]):
        index, line = item
        category = line.get("category")
        if line["name"] in _SUBTOTALS:
            return (_RANK[category], 1, index)
        if category in _RANK:
            return (_RANK[category], 0, index)
        return (3, 0, index) if category else (4, 0, index)

    rows = []
    for _, line in sorted(indexed, key=key):
        status = line.get("status", "산정")
        is_total = line["name"] in ("순공사원가", "총원가", "도급액")
        rows.append({
            "name": line["name"], "category": line.get("category"),
            "basis": _basis_text(line), "amount": line.get("amount") if status != "미산정" else None,
            "status": status, "reason": line.get("reason"), "note": line.get("note"),
            "kind": "subtotal" if line["name"] in _SUBTOTALS else ("total" if is_total else "item"),
            "final": line["name"] == "도급액",
        })
    return rows


def _spec_text(inputs: list[dict]) -> str:
    values = {item["name"]: item["value"] for item in inputs}
    parts = []
    if "structure" in values:
        parts.append(values["structure"])
    if "slump_band" in values:
        parts.append(values["slump_band"])
    if "facility_type" in values or "site_type" in values:
        parts.append(f"{values.get('facility_type', '')}/{values.get('site_type', '').replace('Type-', '')}")
    if "pump_size" in values:
        boom = f"{values['pump_size']} {values.get('placement', '')}".strip()
        parts.append(boom)
    return "·".join(part for part in parts if part)


def bill_row(response: dict) -> dict | None:
    priced = response.get("priced")
    if not priced or not priced.get("reference_amounts"):
        return None
    reference = priced["reference_amounts"]
    unit_prices, amounts = priced.get("unit_prices") or {}, reference.get("subtotals") or {}
    work = response.get("work") or {}
    return {
        "name": f"{work.get('title', '')}({work.get('section_no', '')})" if work else "",
        "spec": _spec_text(response.get("inputs", [])), "unit": "㎥", "quantity": reference.get("volume"),
        "unit_price": {name: unit_prices.get(name) for name in ("재료비", "노무비", "경비")},
        "amount": {name: amounts.get(name) for name in ("재료비", "노무비", "경비")},
        "total": reference.get("total"), "partial": bool(priced.get("partial")),
    }


def unit_price_rows(priced: dict | None) -> list[dict]:
    if not priced:
        return []
    rows = []
    for key in ("lines", "equipment_lines", "cost_lines", "supply_lines"):
        for line in priced.get(key, []):
            if line.get("kind") == "equipment":
                continue  # 장비 합계 줄은 아래 구성 줄(손료·운전원)과 겹친다
            amount = line.get("amount")
            rows.append({"category": line.get("category"), "name": line.get("name"),
                         "unit": line.get("unit") or "", "quantity": line.get("quantity"),
                         "unit_price": line.get("unit_price"), "amount": amount,
                         "status": line.get("status") or ("산정" if amount is not None else "미산정"),
                         "reason": line.get("reason")})
    return rows


def rate_rows(priced: dict | None, statement: dict | None) -> list[dict]:
    """쓴 단가 목록: 노임, 기계경비, 제비율 버전, 관급 자재."""
    if not priced:
        return []
    labor_version = priced.get("rate_version") or {}
    equipment_version = priced.get("equipment_rate_version") or {}
    labor_source = f"{labor_version.get('title', '')}({labor_version.get('publisher', '')})"
    rows = []
    for line in priced.get("lines", []) + priced.get("equipment_lines", []):
        if line.get("unit_price") is None:
            continue
        if line.get("kind") == "labor":
            rows.append({"kind": "노임", "name": f"{line['name']}({line['rate_code']})",
                         "unit": labor_version.get("unit", "원/일"), "price": line["unit_price"],
                         "source": labor_source})
        elif line.get("machine_code") and line.get("rate_code"):
            rows.append({"kind": "노임", "name": f"{line['name']}({line['rate_code']})", "unit": "원/hr",
                         "price": line["unit_price"], "source": labor_source + " 일 노임 ÷ 8시간 환산"})
        elif line.get("machine_code"):
            rows.append({"kind": "기계경비", "name": f"{line['name']} {line.get('machine_spec', '')}".strip(),
                         "unit": "원/hr", "price": line["unit_price"],
                         "source": f"{equipment_version.get('title', '')}({equipment_version.get('publisher', '')})"})
    version = (statement or {}).get("overhead_version")
    if version:
        rows.append({"kind": "제비율", "name": f"조달청 {version['effective_from']} 적용 제비율", "unit": "",
                     "price": None, "source": ", ".join(version.get("source_files", []))})
    for line in priced.get("supply_lines", []):
        rows.append({"kind": "관급 자재(제외)", "name": line["name"], "unit": "", "price": None,
                     "source": line.get("reason") or ""})
    return rows


def add_tables(response: dict) -> dict:
    return {"statement_rows": statement_rows(response.get("statement")), "bill": bill_row(response),
            "unit_rows": unit_price_rows(response.get("priced")),
            "rate_rows": rate_rows(response.get("priced"), response.get("statement"))}


# ---------- 엑셀 ----------

_HEAD = PatternFill("solid", fgColor="E8EEF7")
_STRONG = PatternFill("solid", fgColor="FFF2CC")
_MONEY = "#,##0"
_DECIMAL = "#,##0.####"


def _sheet(book: Workbook, title: str, header: list[str], rows: list[list], widths: list[int],
           money_cols: tuple[int, ...] = (), first: bool = False, top: list[str] | None = None):
    sheet = book.active if first else book.create_sheet()
    sheet.title = title
    for line in top or []:
        sheet.append([line])
    if top:
        sheet.append([])
    header_row = sheet.max_row + 1 if top else 1
    sheet.append(header)
    for cell in sheet[header_row]:
        cell.font, cell.fill = Font(bold=True), _HEAD
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for row in rows:
        sheet.append(row)
        for column in money_cols:
            cell = sheet.cell(row=sheet.max_row, column=column)
            if isinstance(cell.value, (int, float)):
                cell.number_format = _MONEY if isinstance(cell.value, int) else _DECIMAL
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    return sheet


def build_xlsx(response: dict) -> bytes:
    tables = response["tables"]
    statement = response.get("statement") or {}
    conditions = {item["name"]: item["value"] for item in response.get("conditions", [])}
    scale = conditions.get("project_scale")
    scale_text = scale if scale == "이 견적만" else f"{int(scale):,}원"
    top = [f"기준일: {response.get('basis_date') or date.today().isoformat()}",
           f"조건: {conditions.get('work_category')} · {conditions.get('duration')} · "
           f"{conditions.get('contractor_type')} · 전체 공사 규모 {scale_text}",
           DISCLAIMER]
    book = Workbook()

    rows = []
    for row in tables["statement_rows"]:
        rows.append([row["name"], row["basis"], _num(row["amount"]),
                     row["status"], row.get("reason") or row.get("note") or "", row["category"] or ""])
    sheet = _sheet(book, "원가계산서", ["비목", "산출 기준", "금액(원)", "상태", "사유·비고", "구분"],
                   rows, [28, 48, 16, 8, 50, 10], (3,), first=True, top=top)
    for row in sheet.iter_rows(min_row=sheet.max_row - len(rows) + 1):
        if row[0].value == "도급액":
            for cell in row:
                cell.font, cell.fill = Font(bold=True), _STRONG

    bill = tables["bill"] or {}
    bill_rows = []
    if bill:
        bill_rows.append([bill["name"], bill["spec"], bill["unit"], _num(bill["quantity"]),
                          *(_num(bill["unit_price"][n]) for n in ("재료비", "노무비", "경비")),
                          *(_num(bill["amount"][n]) for n in ("재료비", "노무비", "경비")),
                          _num(bill["total"]), "부분 합계(미산정 제외)" if bill["partial"] else ""])
    _sheet(book, "내역서", ["공종", "규격", "단위", "수량", "재료비 단가", "노무비 단가", "경비 단가",
                          "재료비 금액", "노무비 금액", "경비 금액", "합계", "비고"],
           bill_rows, [30, 30, 6, 10, 12, 12, 12, 14, 14, 14, 14, 22], tuple(range(4, 12)))

    _sheet(book, "일위대가", ["구분", "품명", "단위", "수량", "단가", "금액(1㎥당)", "상태", "사유·출처"],
           [[row["category"] or "", row["name"], row["unit"], _num(row["quantity"]), _num(row["unit_price"]),
             _num(row["amount"]), row["status"], row.get("reason") or ""] for row in tables["unit_rows"]],
           [10, 30, 10, 10, 14, 14, 8, 50], (4, 5, 6))

    _sheet(book, "단가대비표", ["구분", "품명", "단위", "단가", "출처"],
           [[row["kind"], row["name"], row["unit"], _num(row["price"]), row["source"]]
            for row in tables["rate_rows"]], [16, 40, 12, 14, 70], (4,))

    result = response.get("result") or {}
    basis = []
    daily = result.get("daily_volume")
    if daily:
        basis.append(["일일시공량", f"{daily['value']} {daily['unit']}", daily["formula"], "; ".join(daily["sources"])])
    if result.get("work_days"):
        basis.append(["작업일수", result["work_days"]["value"], result["work_days"]["formula"], ""])
    for line in result.get("lines", []):
        basis.append([f"{line['name']} 작업조·투입", f"{line['value']} {line['unit']}",
                      f"작업조 {line['crew']}" if line.get("crew") else "", line["source"]])
    for line in result.get("unit_lines", []):
        basis.append([f"{line['name']} 1㎥당", f"{line['applied']} {line['unit']}", line["formula"],
                      f"{line['rule']}; {line['source']}"])
    for item in result.get("not_calculated", []):
        basis.append([item["item"], "미산정", "", item["source"]])
    for note in statement.get("basis_notes", []):
        basis.append(["제비율 기준", "", note, ""])
    _sheet(book, "산출근거", ["항목", "값", "산식·설명", "출처"], basis, [26, 20, 44, 70])

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()

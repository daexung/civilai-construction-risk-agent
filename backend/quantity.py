"""6장 품량 계량: 원문 표에서 노무 품량을 단가 없이 계산한다 (첫 구현).

실행 예:
    python backend/quantity.py --section 6-1-2 --cond 유형=기계비빔타설 --cond 구조물=철근구조물 --quantity 100
    python backend/quantity.py --section 6-1-1 --cond "공법=인력운반 타설" --cond 구조물=철근구조물 --quantity 100 --json
    python backend/quantity.py --section 6-1-2 --cond 유형=기계비빔타설 --cond 구조물=소형구조물 --quantity 8 \\
        --confirm small_structure_scattered=true

범위
  - 계산할 수 있는 조건 조합은 evals/golden_quantity.json의 cases에 있는 것뿐이다(정답을 먼저 적은 사례만 연다).
  - 이번에는 인력(노무) 품량만. 노임·자재·장비 단가와 금액은 다루지 않는다. LLM·검색을 쓰지 않는다.

기준량 규칙 (유리수 Fraction으로 정확히 계산. 반올림·절사하지 않는다)
  per_day  '(일당)' 표: 품량 = 물량 ÷ 일당 시공량 × 작업조 인원          (6-1-1)
  per_unit '(㎥당)' 표: 품량 = 물량 ÷ 기준량(표기의 숫자, 없으면 1) × 원문 수량 (6-1-2)
품량 출력은 정확값(exact: 끝나는 소수 또는 기약분수)과 표시값(display: 순환소수 괄호 표기, 역시 정확)을 나눠 적는다.
몇 자리에서 반올림할지, 금액 반올림 규칙은 정하지 않았다.

원문에서 확인되지 않는 것은 추정하지 않고 거부한다: 지원 절·사례 밖, 표 구조 불확실, 기준 표기 없음·불일치,
조건 누락·원문 표에 없는 값, 맞는 행이 1개가 아님, 값이 비었거나 0 이하·숫자 아님, 물량·단위 오류,
원문 적용 조건(예: 6-1-2 소형구조물)에 대한 명시적 확인값(true)이 없음.
"""

import argparse
import json
import re
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import CHUNKS, PARSED, citation, load  # noqa: E402
from unit_price import VolumeError, parse_volume, safe_console  # noqa: E402

GOLDEN = ROOT / "evals/golden_quantity.json"
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
BASIS_RE = re.compile(r"^\((\d+(?:\.\d+)?)?\s*(㎥|㎡|m|ton|개소|개)당\)$")
UNIT_ALIASES = {"㎥": "㎥", "m3": "㎥", "m³": "㎥"}
USER_INPUT = "사용자 입력"
DISPLAY_RULE = "끝나는 소수는 그대로, 순환소수는 반복 구간을 괄호로 표기한다(예: 5.(45) = 60/11). 반올림하지 않는다."
ROUNDING = "반올림·절사 없음. 정확값은 기약분수 또는 끝나는 소수. 표시 자릿수와 금액 반올림 규칙은 정하지 않았다."

# 원문 표의 '인'을 노임단가(원/인·일)와 곱할 결과 단위로 옮기는 해석. 값은 바꾸지 않는다
UNIT_INTERPRETATION = {
    "per_day": ("원문 '인'은 작업조 인원(명)이고 시공량은 ㎥/일이다. 물량 ÷ 일당 시공량 = 작업 일수이므로 "
                "일수 × 인원 = 인·일(1인이 1일 작업하는 양의 합)로 기록한다."),
    "per_unit": ("원문 '인'은 기준량(㎥)당 인력 품이며 품셈의 인력 품 단위(1인 1일 작업량)로 해석한다. "
                 "물량 ÷ 기준량 × 품 = 인·일로 기록한다."),
}

# 절별 원문 표 명세. 레코드 글자('라벨 | 칸 | 열이름 값 | …')를 이 형식으로만 읽는다
SPECS = {
    "6-1-1": {
        "rule": "per_day", "basis_label": "(일당)", "row_condition": "공법", "trade_re": r"^(\S+)$",
        "column_condition": "구조물", "column_re": r"^시공량\(㎥\) (\S+) (\S+)$", "crew_re": r"^수량 (\S+)$",
        "trades": ["콘크리트공", "보통인부"],
    },
    "6-1-2": {
        "rule": "per_unit", "basis_label": "(㎥당)", "row_condition": "유형", "trade_re": r"^구분 (\S+)$",
        "column_condition": "구조물", "column_re": r"^수량 (\S+) (\S+)$", "crew_re": None,
        "trades": ["콘크리트공", "보통인부"],
        # 원문 [주]가 현장 사실을 적용 기준으로 두는 값. 확인 항목 키에 명시적 true가 있어야 계산한다
        "confirmations": {
            ("구조물", "소형구조물"): {
                "key": "small_structure_scattered",
                "question": "현장이 원문 [주] ②의 소형구조물 적용 조건(소량의 콘크리트 구조물이 산재)에 해당합니까? (true/false)",
                "clause_marker": "소형구조물은",
            },
        },
    },
}


class Refused(Exception):
    """원문으로 확인할 수 없어 계산하지 않음."""


def load_sources() -> tuple[list[dict], list[dict]]:
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    return chunks, records


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


# ---------------- 정확값·표시값 ----------------

def is_terminating(value: Fraction) -> bool:
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def decimal_text(value: Fraction) -> str:
    """정확한 10진 전개. 끝나는 소수면 그대로, 순환소수면 반복 구간을 괄호로(반올림 없음). 양수만."""
    integer, remainder = divmod(value.numerator, value.denominator)
    if remainder == 0:
        return str(integer)
    digits, seen = [], {}
    while remainder and remainder not in seen:
        seen[remainder] = len(digits)
        remainder *= 10
        digits.append(str(remainder // value.denominator))
        remainder %= value.denominator
    if not remainder:
        return f"{integer}.{''.join(digits)}"
    start = seen[remainder]
    return f"{integer}.{''.join(digits[:start])}({''.join(digits[start:])})"


def exact_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return decimal_text(value) if is_terminating(value) else f"{value.numerator}/{value.denominator}"


def quantity_record(value: Fraction) -> dict:
    return {"exact": exact_text(value), "numerator": str(value.numerator), "denominator": str(value.denominator),
            "terminating": is_terminating(value), "display": decimal_text(value), "display_rule": DISPLAY_RULE}


def shown(value: Fraction) -> str:
    """계산식용: 정확값, 순환소수면 표시값을 덧붙인다."""
    text = exact_text(value)
    return text if is_terminating(value) else f"{text} (= {decimal_text(value)})"


def parse_quantity(text: str) -> Fraction:
    """정답 파일의 기대값('10.625' 또는 '60/11')을 정확한 유리수로."""
    return Fraction(text)


# ---------------- 원문 표 읽기 ----------------

def parts_of(record: dict) -> list[str]:
    prefix = f"{record['section']} | "
    text = record["text"][len(prefix):] if record["text"].startswith(prefix) else record["text"]
    return [p.strip() for p in text.split("|")]


def table_model(spec: dict, chunk: dict, records: list[dict]) -> list[dict]:
    """표 청크의 행을 명세대로 읽는다. 비고 행은 따로 둔다."""
    rows = []
    for rid in chunk["record_ids"]:
        parts = parts_of(records[rid])
        if len(parts) < 2 or parts[0] == "비고":
            continue
        trade = re.match(spec["trade_re"], parts[1])
        row = {"record_id": rid, "text": records[rid]["text"], spec["row_condition"]: parts[0],
               "trade": trade.group(1) if trade else None, "unit": None, "crew": [], "columns": {}}
        for part in parts[2:]:
            if (m := re.match(r"^단위 (\S+)$", part)):
                row["unit"] = m.group(1)
            elif spec["crew_re"] and (m := re.match(spec["crew_re"], part)):
                row["crew"].append(m.group(1))
            elif (m := re.match(spec["column_re"], part)):
                row["columns"].setdefault(m.group(1), []).append(m.group(2))
        rows.append(row)
    return rows


def positive_number(values: list[str], what: str) -> Fraction:
    if len(values) != 1 or not NUMBER_RE.match(values[0]):
        raise Refused(f"{what}이 하나의 숫자가 아닙니다: {values}")
    value = Fraction(Decimal(values[0]))
    if value <= 0:
        raise Refused(f"{what}이 0보다 크지 않습니다: {values[0]}")
    return value


def section_notes(section_no: str, chunks: list[dict], records: list[dict], table_chunk: dict) -> dict:
    """절(과 상위 절) 줄글, 표 안 비고를 조항으로 나눠 이번 노무 품량과의 관계로 분류한다. 원문을 그대로 인용한다."""
    parent = section_no.rsplit("-", 1)[0]
    groups = {"included_scope": [], "excluded_separate": [], "conditional": []}
    sources = [(c, " ".join(parts_of(records[r])[-1] for r in c["record_ids"]))
               for c in chunks if c["kind"] == "text" and c["section_no"] in (section_no, parent)]
    notes = [r for r in table_chunk["record_ids"] if parts_of(records[r])[0] == "비고"]
    if notes:
        sources.append((table_chunk, " ".join(parts_of(records[r])[-1] for r in notes)))
    for chunk, text in sources:
        text = text.replace("[주]", " ")
        for clause in re.split(r"(?=[①-⑳◦])|\s(?=-\s)", text):
            clause = clause.strip(" -")
            if len(clause) < 6:
                continue
            if re.search(r"별도\s*계상|추가\s*계상|를 따른다|%로 계상|%를 적용", clause):
                kind = "excluded_separate"
            elif re.search(r"포함한다|포함하고", clause):
                kind = "included_scope"
            elif re.search(r"감하여|적용한다", clause):
                kind = "conditional"
            else:
                continue
            groups[kind].append({"text": clause, "source": citation(chunk)})
    return groups


def refuse(base: dict, reason: str) -> dict:
    return {**base, "status": "refused", "reason": reason, "lines": [], "automated_check": "해당 없음"}


# ---------------- 계산 ----------------

def compute(section_no: str, conditions: dict, work_quantity, unit: str = "㎥",
            confirmations: dict | None = None, sources=None, golden: dict | None = None) -> dict:
    """노무 품량 계산. 결과 status는 'computed' 또는 'refused'.

    confirmations: 원문 적용 조건에 대한 사용자 확인. {확인 항목 키: True/False}. 불리언 True만 승인이다.
    """
    confirmations = dict(confirmations or {})
    base = {"section_no": section_no, "conditions": dict(conditions),
            "confirmations": {k: v for k, v in confirmations.items()},
            "input": {"work_quantity": str(work_quantity), "unit": unit}}
    spec = SPECS.get(section_no)
    if spec is None:
        return refuse(base, f"지원하지 않는 절입니다: {section_no} (지원: {', '.join(SPECS)})")
    try:
        volume = parse_volume(work_quantity)
    except VolumeError as exc:
        return refuse(base, str(exc))
    if UNIT_ALIASES.get(unit) != "㎥":
        return refuse(base, f"물량 단위는 ㎥여야 합니다: {unit!r}")
    base["input"] = {"work_quantity": plain(volume), "unit": "㎥"}
    known_keys = {c["key"] for c in spec.get("confirmations", {}).values()}
    unknown = sorted(set(confirmations) - known_keys)
    if unknown:
        return refuse(base, f"알 수 없는 확인 항목입니다: {', '.join(unknown)} (이 절의 확인 항목: {sorted(known_keys) or '없음'})")
    for key, value in confirmations.items():
        if not isinstance(value, bool):
            return refuse(base, f"확인 항목 '{key}'의 값은 true 또는 false여야 합니다(문장으로 판정하지 않음): {value!r}")

    chunks, records = sources or load_sources()
    golden = golden or load_golden()
    tables = [c for c in chunks if c["kind"] == "table" and c["section_no"] == section_no]
    labeled = [c for c in tables if c["basis"] == spec["basis_label"]]
    if len(labeled) != 1:
        return refuse(base, f"{section_no}에서 기준 표기 {spec['basis_label']}가 붙은 표가 {len(labeled)}개입니다(정확히 1개 필요).")
    chunk = labeled[0]
    base.update(section=chunk["section"], rule=spec["rule"])
    if chunk["structure"] != "ok":
        return refuse(base, f"원문 표 {chunk['chunk_id']}의 구조가 불확실합니다(행 합침 또는 줄 수 불일치).")
    # per_day는 표기가 명세와 같으면 된다. per_unit만 표기에서 기준량(숫자·단위)을 읽는다
    basis_match = BASIS_RE.match(chunk["basis"] or "") if spec["rule"] == "per_unit" else None
    if spec["rule"] == "per_unit" and not basis_match:
        return refuse(base, f"기준 표기에서 기준량을 읽을 수 없습니다: {chunk['basis']!r}")

    rows = table_model(spec, chunk, records)
    options = {spec["row_condition"]: sorted({r[spec["row_condition"]] for r in rows}),
               spec["column_condition"]: sorted({k for r in rows for k in r["columns"]})}
    for name, values in options.items():
        if name not in conditions:
            return refuse(base, f"조건 '{name}'이 없습니다. 원문 표의 값 중 하나를 지정하세요: {', '.join(values)}")
        if conditions[name] not in values:
            return refuse(base, f"조건 '{name}={conditions[name]}'은 원문 표에 없습니다. 가능한 값: {', '.join(values)}")
    extra = sorted(set(conditions) - set(options))
    if extra:
        return refuse(base, f"이 표에 없는 조건입니다: {', '.join(extra)}")

    notes = section_notes(section_no, chunks, records, chunk)
    condition_records = [{"name": name, "value": value, "source": f"원문 표 {chunk['chunk_id']}의 {name} 값"}
                         for name, value in conditions.items()]
    confirmed_clauses = []
    for (name, value), need in spec.get("confirmations", {}).items():
        if conditions.get(name) != value:
            continue
        clause = next((n for n in notes["conditional"] if need["clause_marker"] in n["text"]), None)
        quote = f" 원문: {clause['text']} {clause['source']}" if clause else ""
        answer = confirmations.get(need["key"])
        if answer is None:
            return refuse(base, f"'{value}'은 원문이 현장 조건을 적용 기준으로 둡니다. 확인 항목 '{need['key']}'에 true가 "
                                f"필요합니다(추정하지 않음). 질문: {need['question']}{quote}")
        if answer is not True:
            return refuse(base, f"확인 항목 '{need['key']}'이 false라 '{value}' 품을 적용하지 않습니다.{quote}")
        condition_records.append({"name": f"{value} 적용 조건", "confirmation_key": need["key"], "value": True,
                                  "question": need["question"], "source": USER_INPUT, "original_clause": clause})
        confirmed_clauses.append(clause)

    case = next((c for c in golden["cases"] if c["section_no"] == section_no and c["conditions"] == conditions), None)
    if case is None:
        allowed = [c["conditions"] for c in golden["cases"] if c["section_no"] == section_no]
        return refuse(base, f"정답 사례가 아직 없는 조건 조합이라 계산하지 않습니다. 지원 조합: {allowed}")

    per = Fraction(Decimal(basis_match.group(1) or "1")) if basis_match else None
    per_unit = basis_match.group(2) if basis_match else None
    if spec["rule"] == "per_unit" and per_unit != "㎥":
        return refuse(base, f"기준량 단위({per_unit})가 물량 단위(㎥)와 다릅니다.")
    work = Fraction(volume)
    lines = []
    try:
        for trade in spec["trades"]:
            matched = [r for r in rows if r["trade"] == trade and r[spec["row_condition"]] == conditions[spec["row_condition"]]]
            if len(matched) != 1:
                raise Refused(f"{trade}: 조건에 맞는 원문 행이 {len(matched)}개입니다(정확히 1개 필요).")
            row = matched[0]
            if row["unit"] != "인":
                raise Refused(f"{trade}: 원문 단위가 '인'이 아닙니다: {row['unit']!r}")
            column = conditions[spec["column_condition"]]
            value = positive_number(row["columns"].get(column, []), f"{trade}: '{column}' 열 값")
            if spec["rule"] == "per_day":
                crew = positive_number(row["crew"], f"{trade}: 작업조 인원")
                qty = work / value * crew
                basis = {"rule": "per_day", "label": chunk["basis"], "crew": exact_text(crew), "crew_unit": "인(작업조 인원)",
                         "daily_output": exact_text(value), "daily_output_unit": "㎥/일"}
                formula = f"{exact_text(work)}㎥ ÷ {exact_text(value)}㎥/일 × {exact_text(crew)}인 = {shown(qty)}인·일"
            else:
                qty = work / per * value
                basis = {"rule": "per_unit", "label": chunk["basis"], "per": exact_text(per), "per_unit": per_unit,
                         "rate": exact_text(value), "rate_unit": f"인/{exact_text(per) if per != 1 else ''}{per_unit}"}
                formula = f"{exact_text(work)}㎥ ÷ {exact_text(per)}{per_unit} × {exact_text(value)}인 = {shown(qty)}인·일"
            lines.append({
                "item_kind": "labor", "name": trade, "quantity": quantity_record(qty),
                "source_unit": "인", "result_unit": "인·일", "unit_interpretation": UNIT_INTERPRETATION[spec["rule"]],
                "basis": basis,
                "conditions": {name: conditions[name] for name in options},
                "formula": formula,
                "source": {"section": chunk["section"], "section_no": section_no, "pdf_page": chunk["source"]["page"],
                           "table_id": chunk["source"]["table_id"], "bbox": chunk["source"]["bbox"],
                           "row": row["text"], "record_id": row["record_id"], "basis_record": chunk["basis"],
                           "citation": citation(chunk)},
                "validation": {"automated_check": "통과",
                               "checks": [f"표 구조 {chunk['structure']}", f"기준 표기 {chunk['basis']}", "조건 값이 원문 표에 있음",
                                          "원문 행 1개", "열 값 1개(양수)", "원문 단위 인", "유리수 정확 계산"],
                               "human_review": case["human_review"]},
            })
    except Refused as exc:
        return refuse(base, str(exc))

    return {**base, "status": "computed", "case_id": case["id"], "reason": None,
            "automated_check": "통과", "human_review": case["human_review"],
            "condition_records": condition_records, "lines": lines,
            "labor_scope": {"included_scope": notes["included_scope"],
                            "not_included_separate": notes["excluded_separate"],
                            "conditional_not_applied": [n for n in notes["conditional"] if n not in confirmed_clauses],
                            "statement": "이번 결과는 원문 표의 노무 품량만이다. 별도 계상 항목(양생, 장비 기계경비, 운반비, "
                                         "공구손료·경장비 등)과 할증·감산은 포함하지 않았다."},
            "rounding": ROUNDING}


def report(result: dict) -> str:
    if result["status"] == "refused":
        return f"[거부] {result['section_no']}: {result['reason']}"
    cond = " · ".join(f"{k}={v}" for k, v in result["conditions"].items())
    lines = [f"[품량] {result['section']} | {cond} | {result['input']['work_quantity']}㎥ | 규칙 {result['rule']} "
             f"{result['lines'][0]['basis']['label']}"]
    for line in result["lines"]:
        q = line["quantity"]
        value = q["exact"] if q["terminating"] else f"{q['exact']} (표시 {q['display']})"
        lines.append(f"  {line['name']:6} {value:>8} {line['result_unit']} (원문 단위 {line['source_unit']})"
                     f"   {line['formula']}")
    first = result["lines"][0]
    lines.append(f"  출처 {first['source']['citation']}")
    lines.append(f"  단위 해석: {first['unit_interpretation']}")
    lines.append(f"  값 표기: {result['rounding']}")
    for c in result["condition_records"]:
        if c["source"] == USER_INPUT:
            lines.append(f"  적용 조건(출처 {USER_INPUT}): {c['confirmation_key']}=true, {c['question']}")
    hr = ", ".join(f"{k} {v}" for k, v in result["human_review"].items())
    lines.append(f"  자동 검사: {result['automated_check']} | 사람 검토: {hr}")
    scope = result["labor_scope"]
    lines.append(f"  포함하지 않음: {scope['statement']}")
    for n in scope["not_included_separate"]:
        lines.append(f"    - {n['text']} {n['source']}")
    for n in scope["conditional_not_applied"]:
        lines.append(f"    - (조건 조항, 계산에 반영하지 않음) {n['text']} {n['source']}")
    return "\n".join(lines)


def parse_confirmation(item: str) -> tuple[str, bool]:
    """명령줄 '--confirm 키=true|false'. 그 밖의 값은 오류(문장으로 판정하지 않음)."""
    key, sep, value = item.partition("=")
    value = value.strip().lower()
    if not sep or value not in ("true", "false"):
        raise ValueError(f"--confirm은 키=true 또는 키=false 형식이어야 합니다: {item!r}")
    return key.strip(), value == "true"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--section", required=True)
    parser.add_argument("--cond", action="append", default=[], help="조건 이름=값 (여러 번)")
    parser.add_argument("--quantity", required=True, help="물량(㎥)")
    parser.add_argument("--unit", default="㎥")
    parser.add_argument("--confirm", action="append", default=[], help="원문 적용 조건 확인: 키=true|false")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    safe_console()
    conditions = {}
    for item in args.cond:
        name, sep, value = item.partition("=")
        if not sep:
            parser.error(f"--cond는 이름=값 형식이어야 합니다: {item}")
        conditions[name.strip()] = value.strip()
    try:
        confirmations = dict(parse_confirmation(item) for item in args.confirm)
    except ValueError as exc:
        parser.error(str(exc))
    result = compute(args.section, conditions, args.quantity, args.unit, confirmations)
    print(json.dumps(result, ensure_ascii=True, indent=1) if args.json else report(result))
    return 0 if result["status"] == "computed" else 3


if __name__ == "__main__":
    raise SystemExit(main())

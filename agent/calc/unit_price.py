"""일위대가(노무비) 계산: 6-1-1 '철근구조물 인력운반 타설' 한 사례만.

실행 예:
    python agent/calc/unit_price.py --volume 150 --rates 내_노임단가.json
    python agent/calc/unit_price.py --volume 150       # 단가 파일 없이: 전 직종 미산정
    python agent/calc/unit_price.py --golden           # 회귀: 골든 사례(100㎥)와 기존 노무량 15인·일 대조

흐름
  1. 지원 사례(SUPPORTED_CASE)는 절·공법·구조물이 고정이다. 물량만 사용자 입력이며 parse_volume으로 검증한다.
  2. 노무량은 품량 계산기 quantity.compute가 낸 값을 받는다(apply_prices). 여기서 다시 계산하지 않는다.
     끝나는 소수가 아닌 노무량은 금액 반올림 규칙이 정해지지 않아 금액을 계산하지 않는다.
     골든 사례 경로(calculate)에서는 기존 결과(각 15인·일)와 다르면 멈춘다.
  3. 같은 사례로 검색해, 계산에 쓴 원문 표 청크가 검색 근거에 들어 있는지 확인한다.
  4. 노임단가는 외부 JSON에서만 읽는다. 단가를 추정하거나 기본값을 넣지 않는다. 단가·기준일·출처 중
     하나라도 없으면 그 직종은 '미산정'이다.
  5. 금액 = 노무량 × 단가 (Decimal, 반올림·절사 없음). 1㎥당 값은 작업조 인원 ÷ 일당 시공량으로 따로 보인다.

단가 파일 형식 (숫자는 문자열 또는 JSON 숫자. 둘 다 Decimal로 읽는다):
    {"rates": [{"trade": "콘크리트공", "unit_price": "…", "unit": "원/인·일",
                "basis_date": "YYYY-MM-DD", "source": "공표 기관·문서명"}]}
"""

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "search"))
sys.path.insert(0, str(ROOT / "agent" / "calc"))
from rag import CHUNKS, Index, citation, evidence, load  # noqa: E402
# 입력 보조 함수는 inputs에 있다. 기존 'from unit_price import parse_volume' 등이 그대로 동작하도록 다시 내보낸다
from inputs import VolumeError, parse_volume, safe_console  # noqa: E402,F401
from quantity import compute as compute_quantity, is_terminating, quantity_record  # noqa: E402

GOLDEN = ROOT / "evals/golden_estimate.json"
PRICE_UNIT = "원/인·일"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNCALCULATED = "미산정"

# 이번 범위에서 지원하는 유일한 사례. 물량 외의 조건은 바꿀 수 없다.
SUPPORTED_CASE = {
    "id": "6-1-1-manual-reinforced",
    "section": "6-1-1 레디믹스트콘크리트 타설('24년 보완)",
    "section_no": "6-1-1",
    "pdf_page": 185,
    "printed_page": 129,
    "method": "인력운반 타설",
    "structure": "철근구조물",
    "trades": ["콘크리트공", "보통인부"],
    "assumptions": [
        "인력운반 타설이 가능한 현장으로 가정한다. 공법 적합성을 판정하지 않는다.",
        "개소별 소량 타설 위치의 산재, 소규모 및 기타 할증/생산성 조정은 적용하지 않는다.",
    ],
    "not_calculated": ["공구손료/경장비 비용", "자재비, 기타 장비비", "별도 양생, 표면 마무리, 추가 인력",
                       "간접비, 이윤, 세금", "실제 공기 및 투입 인원 편성"],
}


class RateError(ValueError):
    """단가 파일 자체가 잘못됨(형식·음수·숫자 아님·중복). 계산하지 않고 멈춘다."""


def load_rates(path: Path | None) -> dict:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    return parse_rates(data)


def parse_rates(data: dict) -> dict:
    """{직종: {"unit_price": Decimal|None, "basis_date", "source", "problem"}}. 잘못된 값은 RateError."""
    if not isinstance(data, dict) or not isinstance(data.get("rates"), list):
        raise RateError("단가 파일에는 'rates' 목록이 있어야 합니다.")
    rates = {}
    for n, entry in enumerate(data["rates"], 1):
        trade = (entry.get("trade") or "").strip() if isinstance(entry, dict) else ""
        if not trade:
            raise RateError(f"{n}번째 항목에 직종(trade)이 없습니다.")
        if trade in rates:
            raise RateError(f"직종 '{trade}'가 두 번 있습니다.")
        unit = entry.get("unit", PRICE_UNIT)
        if unit != PRICE_UNIT:
            raise RateError(f"'{trade}' 단가 단위는 '{PRICE_UNIT}'이어야 합니다: {unit!r}")
        raw = entry.get("unit_price")
        price, problem = None, None
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            problem = "단가 없음"
        else:
            if isinstance(raw, bool) or not isinstance(raw, (str, Decimal)):
                raise RateError(f"'{trade}' 단가는 숫자여야 합니다: {raw!r}")
            try:
                price = Decimal(str(raw).replace(",", "").strip())
            except InvalidOperation:
                raise RateError(f"'{trade}' 단가를 숫자로 읽을 수 없습니다: {raw!r}") from None
            if not price.is_finite() or price <= 0:
                raise RateError(f"'{trade}' 단가는 0보다 큰 유한한 수여야 합니다: {raw!r}")
        basis_date = (entry.get("basis_date") or "").strip()
        source = (entry.get("source") or "").strip()
        if price is not None and not DATE_RE.match(basis_date):
            problem, price = "단가 기준일 없음 또는 형식 오류(YYYY-MM-DD)", None
        elif price is not None and not source:
            problem, price = "단가 출처 없음", None
        rates[trade] = {"unit_price": price, "basis_date": basis_date or None, "source": source or None,
                        "problem": problem}
    return rates


def case_query(case: dict = SUPPORTED_CASE) -> str:
    return f"{case['section']} {case['method']} {case['structure']}"


def quantity_conditions(case: dict = SUPPORTED_CASE) -> dict:
    """지원 사례를 품량 계산기(quantity.compute)의 원문 표 조건 이름으로 옮긴다."""
    return {"공법": case["method"], "구조물": case["structure"]}


# 정확한 내부 계산값과 최종 일위대가표의 표시·적용 금액은 다르다. 후자의 규칙은 아직 정하지 않았다
AMOUNT_POLICY = {
    "internal": "품량·1㎥당 품량·금액·합계를 유리수로 정확히 계산한다. 순환소수도 거부하거나 반올림하지 않는다.",
    "display_and_applied_amount": "미정",
    "undecided": ["원 단위 반올림·절사·올림 여부", "적용 단계(직종별 금액, 1㎥당 금액, 합계 중 어디서)", "표시 자릿수"],
}


def legacy_decimal(value: Fraction) -> Decimal | None:
    """기존 Decimal 필드용: 끝나는 소수면 정확한 Decimal, 끝나지 않으면 None(정확값은 exact 필드에 있다)."""
    if not is_terminating(value):
        return None
    with localcontext() as ctx:
        ctx.prec = max(60, len(str(value.numerator)) + len(str(value.denominator)) + 10)
        return (Decimal(value.numerator) / Decimal(value.denominator)).normalize()


def show(value: Decimal | None, exact: dict | None) -> str:
    """사람용 표기: 끝나는 소수는 기존처럼 천 단위 쉼표, 순환소수는 '분수 (= 순환소수 표기)'. 반올림하지 않는다."""
    if exact is None:
        return UNCALCULATED
    if value is not None:
        return won(value)
    return f"{exact['exact']} (= {exact['display']})"


def calculate_case(volume: Decimal, rates: dict, search_index=None, query: str | None = None) -> dict:
    """실행 경로(명령줄·회귀): 검증된 물량으로 품량을 계산기에서 받은 뒤 단가를 적용한다."""
    if not isinstance(volume, Decimal) or not volume.is_finite() or volume <= 0:
        raise VolumeError(f"검증된 양의 Decimal 물량이 필요합니다: {volume!r}")
    labor = compute_quantity(SUPPORTED_CASE["section_no"], quantity_conditions(), str(volume))
    return apply_prices(labor, rates, search_index, query)


def apply_prices(labor: dict, rates: dict, search_index=None, query: str | None = None,
                 case: dict = SUPPORTED_CASE) -> dict:
    """품량 계산기(quantity.compute) 결과에 원문 근거 확인과 노임단가를 붙인다. 품량은 다시 계산하지 않는다.

    query는 검색에 쓸 질문(에이전트가 사용자 질문을 넘긴다). 없으면 사례 조건으로 만든 질의를 쓴다.
    case는 운영에서 항상 SUPPORTED_CASE다. 검사만 순환소수 계산 확인을 위해 다른 사례 정의를 넘긴다.
    모든 값은 유리수로 정확히 계산한다. 기존 Decimal 필드(person_days, amount 등)는 끝나는 소수일 때 채우고,
    정확값은 항상 exact 필드에 둔다. 표시·적용 금액의 반올림 정책은 정하지 않았다(AMOUNT_POLICY).
    """
    if labor.get("status") != "computed":
        raise RuntimeError(f"품량을 계산하지 못했습니다: {labor.get('reason')}")
    if labor["section_no"] != case["section_no"] or labor["conditions"] != quantity_conditions(case):
        raise RuntimeError(f"지원 사례가 아닌 품량 결과입니다: {labor['section_no']} {labor['conditions']}")
    volume = Decimal(labor["input"]["work_quantity"])
    work = Fraction(volume)
    chunks = load(CHUNKS)
    by_id = {c["chunk_id"]: c for c in chunks}
    section_no = case["section_no"]

    # 검색 근거와 연결: 계산에 쓴 원문 표가 검색 근거에 들어 있는지 확인한다
    index = search_index or Index(chunks)
    search_query = query or case_query(case)
    ev = evidence(index, search_query, 3)
    evidence_ids = {c["chunk_id"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]}
    section_chunks = next((g["chunks"] for g in ev["sections"] if g["section_no"] == section_no), [])

    lines = {line["name"]: line for line in labor["lines"]}
    items, checks, exact_amounts = [], [], []
    for trade in case["trades"]:
        line = lines[trade]
        qty = Fraction(line["quantity"]["exact"])
        crew, output = Decimal(line["basis"]["crew"]), Decimal(line["basis"]["daily_output"])
        per_m3 = Fraction(crew) / Fraction(output)
        chunk = by_id[line["source"]["table_id"]]
        checks.append({"trade": trade, "table_chunk": chunk["chunk_id"],
                       "in_search_evidence": chunk["chunk_id"] in evidence_ids,
                       "page_matches_case": chunk["source"]["page"] == case["pdf_page"],
                       "basis": chunk["basis"], "structure": chunk["structure"]})
        rate = rates.get(trade)
        price = rate["unit_price"] if rate else None
        item = {"trade": trade, "person_days": legacy_decimal(qty), "crew": crew, "daily_output_m3": output,
                "person_days_per_m3": legacy_decimal(per_m3), "unit_price": price, "price_unit": PRICE_UNIT,
                "basis_date": rate["basis_date"] if rate else None, "price_source": rate["source"] if rate else None,
                "labor_source": line["source"]["citation"], "labor_row": line["source"]["row"],
                "quantity_exact": line["quantity"]["exact"], "quantity_formula": line["formula"],
                "exact": {"person_days": quantity_record(qty), "person_days_per_m3": quantity_record(per_m3),
                          "amount": None, "amount_per_m3": None}}
        if price is None:
            # 단가가 없어도 정확한 품량(exact.person_days)은 그대로 낸다. 금액만 미산정
            item.update(amount=None, amount_per_m3=None, applied_amount=None, status=UNCALCULATED,
                        reason=(rate or {}).get("problem") or "단가 파일에 이 직종이 없음")
        else:
            amount, amount_m3 = qty * Fraction(price), per_m3 * Fraction(price)
            exact_amounts.append(amount)
            item["exact"].update(amount=quantity_record(amount), amount_per_m3=quantity_record(amount_m3))
            item.update(amount=legacy_decimal(amount), amount_per_m3=legacy_decimal(amount_m3), status="산정",
                        applied_amount={"value": None, "policy": "미정"})
        items.append(item)

    done = [i for i in items if i["status"] == "산정"]
    total_exact = sum(exact_amounts, Fraction(0)) if done else None
    total = legacy_decimal(total_exact) if total_exact is not None else None
    status = "완료" if len(done) == len(items) else ("부분" if done else UNCALCULATED)

    # 같은 절 줄글에서 이번 계산에 넣지 않은 비용 조건(원문 그대로 인용, 계산하지 않음)
    unapplied = []
    for c in section_chunks:
        if c["kind"] != "text":
            continue
        for m in re.finditer(r"[①-⑳][^①-⑳]*?(공구손료[^①-⑳]*)", c["text"]):
            unapplied.append({"text": m.group(0).strip(), "source": citation(c), "status": "미적용"})

    return {"case": case["id"], "section": case["section"], "pdf_page": case["pdf_page"],
            "printed_page": case["printed_page"], "method": case["method"],
            "structure": case["structure"], "volume_m3": volume,
            "search": {"query": search_query, "top3": [c["chunk_id"] for _, c in ev["hits"]]},
            "items": items, "labor_total_status": status, "labor_total": total,
            "labor_total_per_m3": legacy_decimal(total_exact / work) if total_exact is not None else None,
            "exact": {"labor_total": quantity_record(total_exact) if total_exact is not None else None,
                      "labor_total_per_m3": quantity_record(total_exact / work) if total_exact is not None else None},
            "amount_policy": AMOUNT_POLICY,
            "excluded_uncalculated": [i["trade"] for i in items if i["status"] == UNCALCULATED],
            "source_checks": checks, "unapplied_conditions": unapplied,
            "assumptions": case["assumptions"], "not_calculated": case["not_calculated"],
            "quantity": {"calculator": "agent/calc/quantity.py", "case_id": labor["case_id"], "rule": labor["rule"],
                         "automated_check": labor["automated_check"], "human_review": labor["human_review"]},
            "rounding": "반올림·절사 없음(Decimal 정확값)"}


def calculate(rates: dict, search_index=None) -> dict:
    """회귀 경로: 골든 사례(evals/golden_estimate.json, 100㎥)로 계산하고 기존 노무량과 대조한다."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    case = SUPPORTED_CASE
    same = (golden["source"]["section"] == case["section"] and golden["source"]["pdf_page"] == case["pdf_page"]
            and golden["input"]["method"] == case["method"] and golden["input"]["structure"] == case["structure"]
            and list(golden["expected_person_days"]) == case["trades"])
    if not same:
        raise RuntimeError("골든 사례와 지원 사례 정의가 다릅니다.")
    result = calculate_case(parse_volume(golden["input"]["volume_m3"]), rates, search_index)
    for item in result["items"]:
        expected = Decimal(golden["expected_person_days"][item["trade"]])
        if item["person_days"] != expected:
            raise RuntimeError(f"{item['trade']} 노무량 {item['person_days']}이 기존 결과 {expected}와 다릅니다.")
    result["case"] = golden["id"]
    return result


def won(value) -> str:
    if value is None:
        return UNCALCULATED
    text = format(value.normalize(), "f")
    whole, _, frac = text.partition(".")
    return f"{int(whole):,}" + (f".{frac}" if frac else "")


def report(result: dict) -> str:
    lines = [f"일위대가(노무비): {result['section']} | {result['method']} | {result['structure']} {result['volume_m3']}㎥",
             f"원문: PDF {result['pdf_page']}쪽 (인쇄 {result['printed_page']}쪽)", ""]
    for i in result["items"]:
        lines.append(f"[{i['trade']}] {i['status']}" + (f": {i['reason']}" if i["status"] == UNCALCULATED else ""))
        ex = i["exact"]
        lines.append(f"  수량   {show(i['person_days'], ex['person_days'])} 인·일 (= {result['volume_m3']}㎥ ÷ "
                     f"{won(i['daily_output_m3'])}㎥/일 × {won(i['crew'])}인, 1㎥당 "
                     f"{show(i['person_days_per_m3'], ex['person_days_per_m3'])}인)")
        lines.append(f"  단가   {won(i['unit_price'])}" + (f" {i['price_unit']}" if i["unit_price"] is not None else ""))
        lines.append(f"  금액   {show(i['amount'], ex['amount'])}" + (" 원" if ex["amount"] is not None else "")
                     + (f" (1㎥당 {show(i['amount_per_m3'], ex['amount_per_m3'])} 원)" if ex["amount_per_m3"] is not None else ""))
        lines.append(f"  기준일 {i['basis_date'] or '-'} | 단가 출처 {i['price_source'] or '-'}")
        lines.append(f"  노무량 출처 {i['labor_source']}")
    lines.append("")
    total, total_ex = result["labor_total"], result["exact"]["labor_total"]
    label = {"완료": "합계", "부분": "부분 합계", UNCALCULATED: "합계"}[result["labor_total_status"]]
    lines.append(f"{label}: {show(total, total_ex)}" + (" 원" if total_ex is not None else "")
                 + (f" (1㎥당 {show(result['labor_total_per_m3'], result['exact']['labor_total_per_m3'])} 원)"
                    if total_ex is not None else "")
                 + (f": 미산정 제외: {', '.join(result['excluded_uncalculated'])}" if result["excluded_uncalculated"] and total_ex is not None else ""))
    lines.append(f"계산: {result['rounding']}")
    if total_ex is not None:
        lines.append(f"표시·적용 금액: {result['amount_policy']['display_and_applied_amount']} "
                     f"({', '.join(result['amount_policy']['undecided'])}). 위 금액은 정확한 계산값이다.")
    lines.append("")
    lines.append(f"검색 연결: 질의 '{result['search']['query']}' 상위 3 {result['search']['top3']}")
    for c in result["source_checks"]:
        lines.append(f"  {c['trade']}: 표 {c['table_chunk']} 검색 근거 포함 {c['in_search_evidence']}, "
                     f"쪽 일치 {c['page_matches_case']}, 기준 {c['basis']}, 구조 {c['structure']}")
    if result["unapplied_conditions"]:
        lines.append("미적용 조건 (원문 인용, 이번 금액에 넣지 않음):")
        for u in result["unapplied_conditions"]:
            lines.append(f"  - {u['text']} {u['source']}")
    lines.append("이 도구의 범위: 직종별 노무비(노무량 × 입력 단가)만 계산한다. 할증·감산·경비는 넣지 않았다.")
    lines.append("계산하지 않은 항목: " + "; ".join(result["not_calculated"]))
    return "\n".join(lines)


def to_json(result: dict, ascii_only: bool = False) -> str:
    """결과를 JSON 글자로. Decimal은 지수·끝자리 0 없는 문자열로 적는다.

    ascii_only=True(명령줄 --json)면 한글·㎥·① 같은 글자를 \\uXXXX로 적는다. 콘솔 인코딩이 cp949여도
    safe_console의 '?' 대체를 거치지 않으므로, 받는 쪽 json.loads가 원래 글자를 그대로 되살린다.
    """
    return json.dumps(result, ensure_ascii=ascii_only, indent=1,
                      default=lambda v: format(v.normalize(), "f") if isinstance(v, Decimal) else str(v))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--volume", help="철근구조물 인력운반 타설 물량(㎥). 양의 숫자")
    parser.add_argument("--golden", action="store_true", help="회귀: 골든 사례(100㎥)로 계산하고 기존 노무량과 대조")
    parser.add_argument("--rates", type=Path, help="직종별 노임단가 JSON (없으면 전 직종 미산정)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    safe_console()
    if args.golden == (args.volume is not None):
        parser.error("--volume 또는 --golden 중 하나만 지정해야 합니다.")
    try:
        rates = load_rates(args.rates)
        result = calculate(rates) if args.golden else calculate_case(parse_volume(args.volume), rates)
    except (RateError, VolumeError, OSError, json.JSONDecodeError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    print(to_json(result, ascii_only=True) if args.json else report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

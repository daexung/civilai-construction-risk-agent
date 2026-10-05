"""Human and JSON output formatting for calculation results."""

import json
import sys
from decimal import Decimal

UNCALCULATED = "미산정"

def show(value: Decimal | None, exact: dict | None) -> str:
    """사람용 표기: 끝나는 소수는 기존처럼 천 단위 쉼표, 순환소수는 '분수 (= 순환소수 표기)'. 반올림하지 않는다."""
    if exact is None:
        return UNCALCULATED
    if value is not None:
        return won(value)
    return f"{exact['exact']} (= {exact['display']})"


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
        policy = result["amount_policy"]
        rules = ", ".join(f"{r['item']} {r['digit']}{r['unit']} {r['rule']}" for r in policy["confirmed"]["rules"])
        lines.append("위 금액은 정확한 계산값이다(버림 미적용).")
        lines.append(f"  품셈 확인: {rules} ({policy['confirmed']['source']})")
        lines.append(f"  표시·적용 금액: {policy['display_and_applied_amount']}, 정하지 않은 것: "
                     + "; ".join(policy["undecided"]))
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



def safe_console() -> None:
    """Windows 기본 콘솔(cp949)에 없는 글자가 원문 인용 등에 섞여도 출력 중에 멈추지 않게 한다.

    콘솔 인코딩은 바꾸지 않는다. UTF-8이 아닌 출력에서만, 인코딩할 수 없는 글자를 '?'로 대신한다.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and encoding != "utf8":
            stream.reconfigure(errors="replace")

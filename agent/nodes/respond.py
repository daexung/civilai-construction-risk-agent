"""Compose the human response from completed state and calculation result."""

from agent.state import SCOPE, base_response
from agent.tools.calc.format import UNCALCULATED, show, won

def compose(resp: dict, result: dict | None) -> str:
    lines = []
    if resp["status"] == "OUT_OF_SCOPE":
        lines += [f"[지원 범위 밖] {resp['summary']}", f"이 에이전트는 {SCOPE}만 계산합니다."]
        return "\n".join(lines)
    if resp["status"] == "MISSING_INFO":
        lines += ["[계산하지 않음] 계산에 필요한 조건이 부족하거나 모호합니다. 추정값을 넣지 않았습니다.",
                  "다음을 알려 주세요:"]
        lines += [f"  - {m}" for m in resp["missing_fields"] + resp["ambiguities"]]
        lines.append(f"지원 범위: {SCOPE}")
        return "\n".join(lines)
    if resp["status"] == "ERROR":
        return f"[답변하지 않음] {resp['summary']}"

    r = result
    lines.append(f"[결과] {r['section']} | {r['method']} | {r['structure']} {won(r['volume_m3'])}㎥")
    for i in r["items"]:
        ex = i["exact"]
        qty = f"{show(i['person_days'], ex['person_days'])} 인·일"
        if i["status"] == UNCALCULATED:
            lines.append(f"  - {i['trade']}: {qty}, 노임단가 없음 → 노무비 {UNCALCULATED} ({i['reason']})")
        else:
            lines.append(f"  - {i['trade']}: {qty} × {won(i['unit_price'])} {i['price_unit']} = "
                         f"{show(i['amount'], ex['amount'])} 원 (단가 기준일 {i['basis_date']}, 출처 {i['price_source']})")
    total, total_ex = r["labor_total"], r["exact"]["labor_total"]
    if r["labor_total_status"] == "완료":
        lines.append(f"  노무비 합계: {show(total, total_ex)} 원 (1㎥당 "
                     f"{show(r['labor_total_per_m3'], r['exact']['labor_total_per_m3'])} 원)")
    elif r["labor_total_status"] == "부분":
        lines.append(f"  노무비 부분 합계: {show(total, total_ex)} 원 (미산정 제외: {', '.join(r['excluded_uncalculated'])}),"
                     " 전체 노무비가 아닙니다")
    else:
        lines.append(f"  노무비 합계: {UNCALCULATED} (노임단가가 없어 금액을 만들지 않았습니다)")
    first = r["items"][0]
    lines.append(f"[계산식] {won(r['volume_m3'])}㎥ ÷ {won(first['daily_output_m3'])}㎥/일 × 작업조 인원"
                 f" (1㎥당 {show(first['person_days_per_m3'], first['exact']['person_days_per_m3'])}인), "
                 "금액 = 노무량 × 단가, 반올림·절사 없음")
    if total_ex is not None:
        policy = r["amount_policy"]
        rules = ", ".join(f"{p['item']} {p['digit']}{p['unit']} {p['rule']}" for p in policy["confirmed"]["rules"])
        lines.append("[금액 표시] 위 금액은 정확한 계산값이다(버림 미적용). "
                     f"품셈 1-2-2 확인: {rules} (PDF 62쪽). 품량 적용 자릿수·소액 예외 적용 방식은 정하지 않아 "
                     f"표시·적용 금액은 {policy['display_and_applied_amount']}")
    lines.append(f"[근거] {r['section']} PDF {r['pdf_page']}쪽(인쇄 {r['printed_page']}쪽)")
    lines.append(f"  {first['labor_source']} 기준 {r['source_checks'][0]['basis']}")
    lines.append(f"  사용한 행: {first['labor_row']}")
    for i in r["items"][1:]:
        lines.append(f"  사용한 행: {i['labor_row']}")
    s = resp["search"]
    lines.append(f"[검색] {s['method']} 상위 3 {s['top3']} (임베딩 호출 {s['api_calls']}회)")
    if resp["missing_fields"]:
        lines.append("[부족한 항목]")
        lines += [f"  - {m}" for m in resp["missing_fields"]]
    if r["unapplied_conditions"]:
        lines.append("[미적용 조건] (원문 인용, 금액에 넣지 않음)")
        lines += [f"  - {u['text']} {u['source']}" for u in r["unapplied_conditions"]]
    lines.append("[가정] " + " ".join(r["assumptions"]))
    lines.append("[계산하지 않은 항목] " + "; ".join(r["not_calculated"]))
    for w in resp["warnings"]:
        lines.append(f"[주의] {w}")
    return "\n".join(lines)


def finalize(resp: dict, result: dict | None = None) -> dict:
    resp["final_response"] = compose(resp, result)
    return resp


def out_of_scope(reason: str | list[str], inputs: dict | None = None) -> dict:
    if isinstance(reason, list):
        reason = " ".join(reason)
    resp = base_response("OUT_OF_SCOPE", reason)
    if inputs is not None:
        resp["inputs"] = {k: str(v) for k, v in inputs.items()}
    return finalize(resp)


def missing_info(ext: dict) -> dict:
    resp = base_response("MISSING_INFO", "계산 조건이 부족하거나 모호해 계산하지 않았습니다.")
    resp["inputs"] = {k: str(v) for k, v in ext["inputs"].items()}
    resp["missing_fields"], resp["ambiguities"] = ext["missing"], ext["ambiguous"]
    return finalize(resp)


def quantity_refused(labor: dict, inputs: dict) -> dict:
    resp = base_response("ERROR", f"품량을 계산하지 않았습니다: {labor['reason']}")
    resp["inputs"] = {k: str(v) for k, v in inputs.items()}
    return finalize(resp)

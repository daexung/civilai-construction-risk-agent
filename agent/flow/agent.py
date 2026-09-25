"""최소 에이전트: 6-1-1 '철근구조물 인력운반 타설' 한 사례의 노무량·노무비 질의응답.

실행 예:
    python agent/flow/agent.py "철근구조물 150㎥ 레미콘 인력운반 타설 노무비는?" --rates 내_노임단가.json
    python agent/flow/agent.py "레미콘 타설 노무비 알려줘"            # 조건 부족 → 필요한 항목 안내
    python agent/flow/agent.py "…" --offline                            # 임베딩 없이 BM25만

흐름 (v1.0-team의 router → extractor → 비용 노드 → synthesize 구조와 결과 형식을 참고했다.
      지원 범위가 한 사례라 LLM 없이 규칙으로 판정한다)
  route     질문이 지원 사례를 묻는지 판정한다. 다른 공종·공법·구조물이면 OUT_OF_SCOPE
  extract   공법·구조물·물량을 뽑고 검증한다. 없으면 missing_fields, 여럿이거나 불분명하면 ambiguities
            → 하나라도 있으면 계산하지 않고 MISSING_INFO로 되묻는다(검색·API 호출도 하지 않는다)
  retrieve  하이브리드 검색(BM25 + 벡터 RRF)으로 품셈 근거를 찾는다. 임베딩을 쓸 수 없으면 BM25로 대신하고 기록한다
  quantity  quantity_node.quantity_step → calc/quantity.py (원문 표 품량, 유리수 정확 계산). 거부되면 ERROR
  price     unit_price.apply_prices (단가 적용). 계산에 쓴 원문 표가 검색 근거에 없으면 답하지 않는다(ERROR)
  respond   절·쪽·표 위치와 단가 기준일·출처를 붙여 답한다. 단가가 없는 직종은 금액을 만들지 않고 부족 항목으로 알린다
"""

import argparse
import json
import re
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "search"))
sys.path.insert(0, str(ROOT / "agent" / "calc"))
from rag import CHUNKS, Index, load  # noqa: E402
from unit_price import (SUPPORTED_CASE, UNCALCULATED, RateError, VolumeError, apply_prices,  # noqa: E402
                        load_rates, parse_volume, safe_console, show, to_json, won)
from quantity_node import quantity_step  # noqa: E402

SCOPE = "6-1-1 레디믹스트콘크리트 타설 중 '철근구조물 · 인력운반 타설'의 노무량·노무비"

# 지원 사례를 묻는 질문인지: 레미콘 타설 관련 낱말 중 하나는 있어야 한다
DOMAIN_TERMS = ("레미콘", "레디믹스트", "콘크리트 타설", "콘크리트타설", "타설", "6-1-1")
# 다른 절·공종을 가리키는 낱말. 있으면 이번 범위 밖이다
OTHER_WORK = {"펌프": "콘크리트 펌프차 타설(6-1-4)", "현장비빔": "현장비빔타설(6-1-2)", "비빔": "현장비빔타설(6-1-2)",
              "거푸집": "거푸집(6-3)", "철근가공": "철근 가공(6-2)", "철근 가공": "철근 가공(6-2)",
              "철근조립": "철근 조립(6-2)", "철근 조립": "철근 조립(6-2)", "표면 마무리": "표면 마무리(6-1-3)",
              "PC": "조립식 구조물(6-7)", "PSC": "포스트텐션(6-4)"}
MANUAL_RE = re.compile(r"인력\s*운반|손수레")
EQUIPMENT_RE = re.compile(r"장비\s*사용|굴착기")
REINFORCED_RE = re.compile(r"철근\s*(?:콘크리트\s*)?구조물|철근\s*콘크리트|RC\s*구조")
PLAIN_RE = re.compile(r"무근")
# NFKC로 ㎥·m³ → m3 로 맞춘 뒤 찾는다
VOLUME_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(?:m3|세제곱\s*미터|입방\s*미터|루베)")
OTHER_UNIT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(m2|평|톤|ton|t\b|kg|개소|개|m(?!3))")
BARE_NUMBER_RE = re.compile(r"(?<![\w.,-])(\d[\d,]*(?:\.\d+)?)(?![\d,.]*\s*(?:m\d?|세제곱|입방|루베|평|톤|ton|t\b|kg|개|%|인|일|년|월))")


def plain(value: Decimal | None) -> str | None:
    """Decimal → 지수·끝자리 0 없는 문자열 (22500.0 → '22500'). 값은 바꾸지 않는다."""
    return None if value is None else format(value.normalize(), "f")


def base_response(status: str, summary: str) -> dict:
    """v1.0-team 비용 노드의 결과 형식을 따른다."""
    return {"agent_name": "labor_unit_price", "domain": "노무비(일위대가)", "status": status, "summary": summary,
            "scope": SCOPE, "inputs": {}, "missing_fields": [], "ambiguities": [], "cost_items": [],
            "total_cost": None, "warnings": [], "assumptions": [], "excluded_items": [], "evidence": [],
            "search": None, "final_response": ""}


# ---------------- route / extract ----------------

def route(query: str) -> tuple[str, str | None]:
    """('REPORT', None) 또는 ('OUT_OF_SCOPE', 이유)."""
    text = unicodedata.normalize("NFKC", query)
    others = sorted({name for word, name in OTHER_WORK.items() if word in text})
    if others:
        return "OUT_OF_SCOPE", f"지원하지 않는 공종·공법입니다: {', '.join(others)}"
    other_sections = [s for s in re.findall(r"\d+-\d+(?:-\d+)?", text) if s != "6-1-1"]
    if other_sections:
        return "OUT_OF_SCOPE", f"지원하지 않는 절입니다: {', '.join(other_sections)}"
    if not any(term in text for term in DOMAIN_TERMS):
        return "OUT_OF_SCOPE", "레미콘(레디믹스트콘크리트) 타설 질문이 아닙니다"
    return "REPORT", None


def extract(query: str) -> dict:
    """{'inputs', 'missing', 'ambiguous', 'unsupported'}. 값을 추측해서 채우지 않는다."""
    text = unicodedata.normalize("NFKC", query)
    inputs, missing, ambiguous, unsupported = {}, [], [], []

    manual, equipment = bool(MANUAL_RE.search(text)), bool(EQUIPMENT_RE.search(text))
    if manual and equipment:
        ambiguous.append("타설 공법: '인력운반'과 '장비사용'이 함께 있습니다. 하나를 정해 주세요.")
    elif equipment:
        unsupported.append("타설 공법 '장비사용 타설'은 지원 범위 밖입니다(인력운반 타설만 지원).")
    elif manual:
        inputs["method"] = SUPPORTED_CASE["method"]
    else:
        missing.append("타설 공법: 인력운반 타설인지 알려 주세요.")

    reinforced, plain = bool(REINFORCED_RE.search(text)), bool(PLAIN_RE.search(text))
    if reinforced and plain:
        ambiguous.append("구조물 구분: '철근구조물'과 '무근구조물'이 함께 있습니다. 하나를 정해 주세요.")
    elif plain:
        unsupported.append("구조물 구분 '무근구조물'은 지원 범위 밖입니다(철근구조물만 지원).")
    elif reinforced:
        inputs["structure"] = SUPPORTED_CASE["structure"]
    elif "철근" in text:
        ambiguous.append("구조물 구분: '철근'만으로는 철근구조물(철근콘크리트) 타설인지 알 수 없습니다.")
    else:
        missing.append("구조물 구분: 철근구조물인지 알려 주세요.")

    volumes = VOLUME_RE.findall(text)
    distinct = sorted({v.replace(",", "") for v in volumes}, key=lambda v: (len(v), v))
    if len(distinct) > 1:
        ambiguous.append(f"물량: 서로 다른 값이 {len(distinct)}개 있습니다({', '.join(distinct)}㎥). 하나를 정해 주세요.")
    elif len(distinct) == 1:
        try:
            inputs["volume_m3"] = parse_volume(volumes[0])
        except VolumeError as exc:
            ambiguous.append(f"물량: {exc}")
    else:
        other = OTHER_UNIT_RE.findall(text)
        bare = [n for n in BARE_NUMBER_RE.findall(text.replace("6-1-1", ""))]
        if other:
            ambiguous.append(f"물량 단위: ㎥가 아닌 단위({', '.join(u for _, u in other)})입니다. 타설 물량을 ㎥로 알려 주세요.")
        elif bare:
            ambiguous.append(f"물량 단위: 숫자({', '.join(bare)})에 단위가 없습니다. ㎥ 단위 물량인지 알려 주세요.")
        else:
            missing.append("물량: 타설할 콘크리트 물량(㎥)을 알려 주세요.")
    return {"inputs": inputs, "missing": missing, "ambiguous": ambiguous, "unsupported": unsupported}


# ---------------- retrieve ----------------

def make_search_index(offline: bool, hybrid_factory=None):
    """(검색 인덱스, 방식 이름, 경고). 하이브리드를 만들 수 없으면 BM25로 대신한다."""
    bm25 = Index(load(CHUNKS))
    if offline:
        return bm25, "bm25(오프라인 지정)", None
    try:
        if hybrid_factory is None:
            from hybrid import HybridIndex
            hybrid_factory = HybridIndex
        return hybrid_factory(bm25=bm25), "hybrid", None
    except Exception as exc:  # noqa: BLE001 - 패키지·벡터 파일 문제
        return bm25, "bm25(대체)", f"하이브리드 검색을 준비하지 못해 BM25로 대신했습니다: {type(exc).__name__}"


class _Fallback:
    """하이브리드 검색이 질문 처리 중 실패하면(키 없음·호출 한도·네트워크) BM25로 한 번 대신한다."""

    def __init__(self, primary, bm25):
        self.primary, self.bm25 = primary, bm25
        self.chunks = primary.chunks
        self.used, self.error = "hybrid", None

    def search(self, query, k=5):
        try:
            return self.primary.search(query, k)
        except Exception as exc:  # noqa: BLE001
            self.used, self.error = "bm25(대체)", f"{type(exc).__name__}: {str(exc)[:120]}"
            return self.bm25.search(query, k)


# ---------------- respond ----------------

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
        lines.append(f"[금액 표시] 위 금액은 정확한 계산값이다. 일위대가표의 표시·적용 금액(원 단위 반올림·절사 등)은 "
                     f"{r['amount_policy']['display_and_applied_amount']}")
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


def answer(query: str, rates: dict | None = None, offline: bool = False, hybrid_factory=None) -> dict:
    rates = rates or {}
    intent, reason = route(query)
    if intent == "OUT_OF_SCOPE":
        resp = base_response("OUT_OF_SCOPE", reason)
        resp["final_response"] = compose(resp, None)
        return resp

    ext = extract(query)
    if ext["unsupported"]:
        resp = base_response("OUT_OF_SCOPE", " ".join(ext["unsupported"]))
        resp["inputs"] = {k: str(v) for k, v in ext["inputs"].items()}
        resp["final_response"] = compose(resp, None)
        return resp
    if ext["missing"] or ext["ambiguous"]:
        resp = base_response("MISSING_INFO", "계산 조건이 부족하거나 모호해 계산하지 않았습니다.")
        resp["inputs"] = {k: str(v) for k, v in ext["inputs"].items()}
        resp["missing_fields"], resp["ambiguities"] = ext["missing"], ext["ambiguous"]
        resp["final_response"] = compose(resp, None)
        return resp

    index, method, warning = make_search_index(offline, hybrid_factory)
    search = _Fallback(index, index.bm25) if method == "hybrid" else index
    labor = quantity_step(ext["inputs"])          # 품량 단계: calc/quantity.py가 계산
    if labor["status"] != "computed":
        resp = base_response("ERROR", f"품량을 계산하지 않았습니다: {labor['reason']}")
        resp["inputs"] = {k: str(v) for k, v in ext["inputs"].items()}
        resp["final_response"] = compose(resp, None)
        return resp
    result = apply_prices(labor, rates, search_index=search, query=query)   # 단가 단계
    used = search.used if isinstance(search, _Fallback) else method
    api_calls = getattr(index, "api_calls", 0)
    resp = base_response("OK", "")
    resp["inputs"] = {k: str(v) for k, v in ext["inputs"].items()}
    resp["search"] = {"method": used, "top3": result["search"]["top3"], "api_calls": api_calls}
    if warning:
        resp["warnings"].append(warning)
    if isinstance(search, _Fallback) and search.error:
        resp["warnings"].append(f"하이브리드 검색 실패로 BM25로 대신했습니다: {search.error}")

    if not all(c["in_search_evidence"] and c["page_matches_case"] for c in result["source_checks"]):
        resp["status"] = "ERROR"
        resp["summary"] = ("검색 근거에서 계산에 쓸 원문 표(6-1-1, PDF 185쪽 p185-t0)를 확인하지 못해 답하지 않았습니다. "
                           f"검색 상위 3: {result['search']['top3']}")
        resp["final_response"] = compose(resp, result)
        return resp

    for i in result["items"]:
        resp["cost_items"].append({"trade": i["trade"], "person_days": plain(i["person_days"]),
                                   "unit_price": plain(i["unit_price"]), "amount": plain(i["amount"]),
                                   "status": i["status"], "basis_date": i["basis_date"],
                                   "price_source": i["price_source"], "labor_source": i["labor_source"],
                                   "person_days_exact": i["exact"]["person_days"]["exact"],
                                   "amount_exact": i["exact"]["amount"]["exact"] if i["exact"]["amount"] else None,
                                   "applied_amount": i["applied_amount"]})
        if i["status"] == UNCALCULATED:
            resp["missing_fields"].append(f"노임단가({i['trade']}): 단가·기준일(YYYY-MM-DD)·출처 ({i['reason']})")
    resp["evidence"] = [{"chunk_id": c["table_chunk"], "citation": result["items"][0]["labor_source"],
                         "basis": c["basis"]} for c in result["source_checks"][:1]]
    resp["assumptions"] = result["assumptions"]
    resp["excluded_items"] = result["not_calculated"] + [u["text"] for u in result["unapplied_conditions"]]
    resp["total_cost"] = plain(result["labor_total"])
    resp["total_cost_exact"] = result["exact"]["labor_total"]["exact"] if result["exact"]["labor_total"] else None
    resp["amount_policy"] = result["amount_policy"]
    resp["status"] = "OK" if result["labor_total_status"] == "완료" else "PARTIAL"
    resp["summary"] = {"완료": "노무량과 노무비를 산출했습니다.",
                       "부분": "노무량은 산출했고, 노임단가가 없는 직종의 노무비는 미산정입니다.",
                       UNCALCULATED: "노무량은 산출했고, 노임단가가 없어 노무비는 미산정입니다."}[result["labor_total_status"]]
    resp["final_response"] = compose(resp, result)
    return resp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--rates", type=Path, help="직종별 노임단가 JSON (evals/labor_rates.template.json 형식)")
    parser.add_argument("--offline", action="store_true", help="임베딩 없이 BM25만 사용")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    safe_console()
    try:
        rates = load_rates(args.rates)
    except (RateError, OSError, json.JSONDecodeError) as exc:
        print(f"단가 입력 오류: {exc}", file=sys.stderr)
        return 2
    resp = answer(args.query, rates, offline=args.offline)
    print(to_json(resp, ascii_only=True) if args.json else resp["final_response"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

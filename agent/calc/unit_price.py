"""일위대가(노무비) 계산: 6-1-1 '철근구조물 인력운반 타설' 한 사례만.

실행 예:
    python agent/calc/unit_price.py --volume 150 --rates 내_노임단가.json
    python agent/calc/unit_price.py --volume 150       # 단가 파일 없이: 전 직종 미산정
    python agent/calc/unit_price.py --golden           # 회귀: 골든 사례(100㎥)와 기존 노무량 15인·일 대조

흐름
  1. 지원 사례(SUPPORTED_CASE)는 절·공법·구조물이 고정이다. 물량만 사용자 입력이며 parse_volume으로 검증한다.
  2. 노무량은 rag.estimate_labor로 구한다(구조 확인한 표·'(일당)' 기준·행 1개일 때만).
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
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent" / "search"))
from rag import CHUNKS, PARSED, Index, citation, estimate_labor, evidence, load  # noqa: E402

GOLDEN = ROOT / "evals/golden_estimate.json"
PRICE_UNIT = "원/인·일"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNCALCULATED = "미산정"
VOLUME_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$")

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


class VolumeError(ValueError):
    """물량 입력이 계산에 쓸 수 없는 값."""


def parse_volume(value) -> Decimal:
    """사용자 물량(㎥)을 검증한다. 양의 10진수만 받는다(쉼표 자리 구분 허용, 부호·지수·NaN 거부)."""
    text = str(value).strip() if value is not None else ""
    if not VOLUME_RE.match(text):
        raise VolumeError(f"물량은 양의 숫자(㎥)여야 합니다: {value!r}")
    volume = Decimal(text.replace(",", ""))
    if volume <= 0:
        raise VolumeError(f"물량은 0보다 커야 합니다: {value!r}")
    return volume


def safe_console() -> None:
    """Windows 기본 콘솔(cp949)에 없는 글자가 원문 인용 등에 섞여도 출력 중에 멈추지 않게 한다.

    콘솔 인코딩은 바꾸지 않는다. UTF-8이 아닌 출력에서만, 인코딩할 수 없는 글자를 '?'로 대신한다.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and encoding != "utf8":
            stream.reconfigure(errors="replace")


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


def calculate_case(volume: Decimal, rates: dict, search_index=None, query: str | None = None) -> dict:
    """실행 경로: 검증된 사용자 물량으로 지원 사례의 노무량·노무비를 계산한다.

    query는 검색에 쓸 질문(에이전트가 사용자 질문을 넘긴다). 없으면 사례 조건으로 만든 질의를 쓴다.
    """
    if not isinstance(volume, Decimal) or not volume.is_finite() or volume <= 0:
        raise VolumeError(f"검증된 양의 Decimal 물량이 필요합니다: {volume!r}")
    case = SUPPORTED_CASE
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    section_no = case["section_no"]
    column = f"시공량(㎥) {case['structure']}"

    # 3. 검색 근거와 연결
    index = search_index or Index(chunks)
    search_query = query or case_query()
    ev = evidence(index, search_query, 3)
    evidence_ids = {c["chunk_id"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]}
    section_chunks = next((g["chunks"] for g in ev["sections"] if g["section_no"] == section_no), [])

    items, checks = [], []
    for trade in case["trades"]:
        labor = estimate_labor(chunks, records, section_no, case["method"], trade, column, str(volume))
        if labor["status"] != "ok":
            raise RuntimeError(f"{trade} 노무량을 계산할 수 없습니다: {labor['reason']}")
        person_days = Decimal(labor["person_days"])
        chunk = next(c for c in chunks if c["kind"] == "table"
                     and any(records[r]["text"] == labor["row"] for r in c["record_ids"]))
        checks.append({"trade": trade, "table_chunk": chunk["chunk_id"],
                       "in_search_evidence": chunk["chunk_id"] in evidence_ids,
                       "page_matches_case": chunk["source"]["page"] == case["pdf_page"],
                       "basis": chunk["basis"], "structure": chunk["structure"]})
        crew, output = Decimal(labor["crew"]), Decimal(labor["daily_output"])
        per_m3 = crew / output
        rate = rates.get(trade)
        price = rate["unit_price"] if rate else None
        item = {"trade": trade, "person_days": person_days, "crew": crew, "daily_output_m3": output,
                "person_days_per_m3": per_m3, "unit_price": price, "price_unit": PRICE_UNIT,
                "basis_date": rate["basis_date"] if rate else None, "price_source": rate["source"] if rate else None,
                "labor_source": citation(chunk), "labor_row": labor["row"]}
        if price is None:
            item.update(amount=None, amount_per_m3=None, status=UNCALCULATED,
                        reason=(rate or {}).get("problem") or "단가 파일에 이 직종이 없음")
        else:
            item.update(amount=person_days * price, amount_per_m3=per_m3 * price, status="산정")
        items.append(item)

    done = [i for i in items if i["status"] == "산정"]
    total = sum((i["amount"] for i in done), Decimal(0)) if done else None
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
            "labor_total_per_m3": (total / volume) if total is not None else None,
            "excluded_uncalculated": [i["trade"] for i in items if i["status"] == UNCALCULATED],
            "source_checks": checks, "unapplied_conditions": unapplied,
            "assumptions": case["assumptions"], "not_calculated": case["not_calculated"],
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
        lines.append(f"  수량   {won(i['person_days'])} 인·일 (= {result['volume_m3']}㎥ ÷ {won(i['daily_output_m3'])}㎥/일 "
                     f"× {won(i['crew'])}인, 1㎥당 {won(i['person_days_per_m3'])}인)")
        lines.append(f"  단가   {won(i['unit_price'])}" + (f" {i['price_unit']}" if i["unit_price"] is not None else ""))
        lines.append(f"  금액   {won(i['amount'])}" + (" 원" if i["amount"] is not None else "")
                     + (f" (1㎥당 {won(i['amount_per_m3'])} 원)" if i["amount_per_m3"] is not None else ""))
        lines.append(f"  기준일 {i['basis_date'] or '-'} | 단가 출처 {i['price_source'] or '-'}")
        lines.append(f"  노무량 출처 {i['labor_source']}")
    lines.append("")
    total = result["labor_total"]
    label = {"완료": "합계", "부분": "부분 합계", UNCALCULATED: "합계"}[result["labor_total_status"]]
    lines.append(f"{label}: {won(total)}" + (" 원" if total is not None else "")
                 + (f" (1㎥당 {won(result['labor_total_per_m3'])} 원)" if total is not None else "")
                 + (f": 미산정 제외: {', '.join(result['excluded_uncalculated'])}" if result["excluded_uncalculated"] and total is not None else ""))
    lines.append(f"계산: {result['rounding']}")
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

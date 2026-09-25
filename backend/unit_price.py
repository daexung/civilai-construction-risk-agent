"""일위대가(노무비) 계산: 6-1-1 '철근구조물 100㎥ 인력운반 타설' 한 사례만.

실행 예:
    python backend/unit_price.py --rates 내_노임단가.json
    python backend/unit_price.py                    # 단가 파일 없이: 전 직종 미산정
    python backend/unit_price.py --rates … --json   # 기계가 읽는 형식

흐름
  1. 사례 정의는 evals/golden_estimate.json (절·공법·구조물·물량·기대 노무량)을 그대로 쓴다.
  2. 노무량은 rag.estimate_labor로 구한다(구조 확인한 표·'(일당)' 기준·행 1개일 때만). 기대값(15인·일)과
     다르면 멈춘다.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import CHUNKS, PARSED, Index, citation, estimate_labor, evidence, load  # noqa: E402

CASE = ROOT / "evals/golden_estimate.json"
PRICE_UNIT = "원/인·일"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNCALCULATED = "미산정"


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


def case_query(case: dict) -> str:
    return f"{case['source']['section']} {case['input']['method']} {case['input']['structure']}"


def calculate(rates: dict, search_index=None) -> dict:
    case = json.loads(CASE.read_text(encoding="utf-8"))
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    section_no = case["source"]["section"].split()[0]
    volume = Decimal(case["input"]["volume_m3"])
    column = f"시공량(㎥) {case['input']['structure']}"

    # 3. 검색 근거와 연결
    index = search_index or Index(chunks)
    ev = evidence(index, case_query(case), 3)
    evidence_ids = {c["chunk_id"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]}
    section_chunks = next((g["chunks"] for g in ev["sections"] if g["section_no"] == section_no), [])

    items, checks = [], []
    for trade, expected in case["expected_person_days"].items():
        labor = estimate_labor(chunks, records, section_no, case["input"]["method"], trade, column,
                               case["input"]["volume_m3"])
        if labor["status"] != "ok":
            raise RuntimeError(f"{trade} 노무량을 계산할 수 없습니다: {labor['reason']}")
        person_days = Decimal(labor["person_days"])
        if person_days != Decimal(expected):
            raise RuntimeError(f"{trade} 노무량 {person_days}이 기존 결과 {expected}와 다릅니다.")
        chunk = next(c for c in chunks if c["kind"] == "table"
                     and any(records[r]["text"] == labor["row"] for r in c["record_ids"]))
        checks.append({"trade": trade, "table_chunk": chunk["chunk_id"],
                       "in_search_evidence": chunk["chunk_id"] in evidence_ids,
                       "page_matches_case": chunk["source"]["page"] == case["source"]["pdf_page"],
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

    return {"case": case["id"], "section": case["source"]["section"], "pdf_page": case["source"]["pdf_page"],
            "printed_page": case["source"]["printed_page"], "method": case["input"]["method"],
            "structure": case["input"]["structure"], "volume_m3": volume,
            "search": {"query": case_query(case), "top3": [c["chunk_id"] for _, c in ev["hits"]]},
            "items": items, "labor_total_status": status, "labor_total": total,
            "labor_total_per_m3": (total / volume) if total is not None else None,
            "excluded_uncalculated": [i["trade"] for i in items if i["status"] == UNCALCULATED],
            "source_checks": checks, "unapplied_conditions": unapplied,
            "assumptions": case["assumptions"], "not_calculated": case["not_calculated"],
            "rounding": "반올림·절사 없음(Decimal 정확값)"}


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
    lines.append("사례 정의(golden_estimate.json)의 미계산 항목: " + "; ".join(result["not_calculated"]))
    return "\n".join(lines)


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1,
                      default=lambda v: format(v.normalize(), "f") if isinstance(v, Decimal) else str(v))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rates", type=Path, help="직종별 노임단가 JSON (없으면 전 직종 미산정)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    safe_console()
    try:
        result = calculate(load_rates(args.rates))
    except (RateError, OSError, json.JSONDecodeError) as exc:
        print(f"단가 입력 오류: {exc}", file=sys.stderr)
        return 2
    print(to_json(result) if args.json else report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

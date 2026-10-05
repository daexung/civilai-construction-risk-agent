"""Legacy labor estimate, retained for regression checks only."""

from decimal import Decimal, InvalidOperation
from agent.tools.search.bm25 import citation

def one_value(parts: list[str], prefix: str) -> Decimal:
    values = [p[len(prefix):] for p in parts if p.startswith(prefix)]
    if len(values) != 1:
        raise ValueError(f"'{prefix.strip()}' 값이 정확히 1개여야 합니다. 실제: {values}")
    value = Decimal(values[0].replace(",", ""))
    if not value.is_finite() or value <= 0:
        raise ValueError(f"'{prefix.strip()}' 값이 양수가 아닙니다: {values[0]}")
    return value


def estimate_labor(chunks: list[dict], records: list[dict], section: str, method: str | None,
                   trade: str, column: str, volume: str) -> dict:
    """직종 노무량(인·일) = 물량 ÷ 일당 시공량 × 작업조 인원.

    자동 계산은 아래를 모두 만족할 때만 한다. 하나라도 어긋나면 계산하지 않고 이유와 출처를 돌려준다.
      - 그 절에서 조건(method)·직종(trade)에 맞는 행이 정확히 한 표, 한 행
      - 그 표의 구조가 ok (행 합침·줄 수 불일치로 표시된 행이 없음)
      - 표 바로 위 기준 표기가 '(일당)'
      - 행에 '단위 인', '수량 x', '{column} y'가 각각 하나
    """
    tables = [c for c in chunks if c["kind"] == "table" and c["section_no"] == section]
    matches, loose = [], []
    for c in tables:
        for rid in c["record_ids"]:
            parts = [p.strip() for p in records[rid]["text"].split("|")]
            if method is not None and method not in parts:
                continue
            if trade in parts:
                matches.append((c, rid, parts))
            if any(trade in p for p in parts[1:]):
                # '형틀목공 보통인부'처럼 합쳐진 라벨 안에 든 경우도 모은다
                loose.append((c, rid))
    base = {"section": section, "method": method, "trade": trade, "column": column, "volume": volume}
    uncertain = [(c, rid) for c, rid in loose if rid in c["uncertain_record_ids"]]
    if uncertain:
        return {**base, "status": "refused", "sources": sorted({citation(c) for c, _ in uncertain}),
                "reason": "해당 직종이 구조가 불확실한 행(행 합침 또는 줄 수 불일치)에 있습니다. 원문 표를 확인해야 합니다.",
                "uncertain_rows": [records[rid]["text"] for _, rid in uncertain]}
    if len(matches) != 1:
        return {**base, "status": "refused", "reason": f"조건에 맞는 행이 {len(matches)}개입니다(정확히 1개 필요).",
                "sources": [citation(c) for c, _, _ in matches] or [citation(c) for c in tables]}
    chunk, rid, parts = matches[0]
    src = [citation(chunk)]
    if chunk["structure"] != "ok":
        return {**base, "status": "refused", "sources": src,
                "reason": "원문 표 구조가 불확실합니다(같은 표에 행 합침 또는 줄 수 불일치가 있음). 원문 표를 확인해야 합니다.",
                "uncertain_rows": [records[i]["text"] for i in chunk["uncertain_record_ids"]]}
    if chunk["basis"] != "(일당)":
        return {**base, "status": "refused", "sources": src,
                "reason": f"표의 기준 표기가 '(일당)'이 아닙니다: {chunk['basis']}"}
    if "단위 인" not in parts:
        return {**base, "status": "refused", "sources": src, "reason": "인력 단위(인)가 아닙니다."}
    try:
        crew = one_value(parts, "수량 ")
        output = one_value(parts, f"{column} ")
        days = Decimal(volume) / output * crew
    except (ValueError, InvalidOperation) as exc:
        return {**base, "status": "refused", "sources": src, "reason": str(exc)}
    return {**base, "status": "ok", "sources": src, "row": records[rid]["text"],
            "crew": str(crew), "daily_output": str(output), "person_days": str(days.normalize()),
            "note": "고정 조건의 노무량 환산만 한다. 할증·감산, 단가·금액은 적용하지 않았다."}


def main() -> None:
    import argparse
    import json

    from agent.tools.search.bm25 import CHUNKS, PARSED, load

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["estimate"])
    parser.add_argument("--section", required=True)
    parser.add_argument("--method")
    parser.add_argument("--trade", required=True)
    parser.add_argument("--column", required=True)
    parser.add_argument("--volume", required=True)
    args = parser.parse_args()
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = estimate_labor(chunks, records, args.section, args.method, args.trade, args.column, args.volume)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

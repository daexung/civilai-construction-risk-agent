"""저장된 파싱 결과로 고정 조건의 노무량 환산 사례를 검사한다.

실행: python evals/check_estimate.py
PDF 재파싱, 외부 API, DB 없이 실행한다. 전체 견적의 정답 검사가 아니다.
"""

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).with_name("golden_estimate.json")


def one_value(parts: list[str], prefix: str) -> Decimal:
    values = [part[len(prefix):] for part in parts if part.startswith(prefix)]
    if len(values) != 1:
        raise ValueError(f"{prefix!r}: 값이 정확히 1개 필요합니다. 실제: {values}")
    value = Decimal(values[0])
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{prefix!r}: 유한한 양수여야 합니다.")
    return value


def check_case(records: list[dict], case: dict) -> dict[str, Decimal]:
    source, inputs = case["source"], case["input"]
    scoped = [r for r in records if r["page"] == source["pdf_page"]
              and r["section"] == source["section"]]
    # 숫자만 같아도 '일당' 기준이 누락되면 환산 근거가 완전하지 않다.
    if not any("(일당)" in [p.strip() for p in r["text"].split("|")] for r in scoped):
        raise ValueError("선택한 절에서 일당 기준을 찾지 못했습니다.")

    volume = Decimal(inputs["volume_m3"])
    result = {}
    for trade, expected_crew in case["expected_basis"]["crew"].items():
        candidates = []
        for record in scoped:
            parts = [p.strip() for p in record["text"].split("|")]
            if inputs["method"] in parts and trade in parts:
                candidates.append(parts)
        if len(candidates) != 1:
            raise ValueError(f"{trade}: 레코드 1개가 필요합니다. 실제: {len(candidates)}")
        parts = candidates[0]
        if "단위 인" not in parts:
            raise ValueError(f"{trade}: 인력 단위가 없거나 달라졌습니다.")
        crew = one_value(parts, "수량 ")
        output = one_value(parts, f"시공량(㎥) {inputs['structure']} ")
        if crew != Decimal(expected_crew):
            raise ValueError(f"{trade}: 작업조 수량 불일치: {crew} != {expected_crew}")
        expected_output = Decimal(case["expected_basis"]["daily_output_m3"])
        if output != expected_output:
            raise ValueError(f"{trade}: 일당 시공량 불일치: {output} != {expected_output}")
        person_days = volume / output * crew
        expected = Decimal(case["expected_person_days"][trade])
        if person_days != expected:
            raise ValueError(f"{trade}: 노무량 불일치: {person_days} != {expected}")
        result[trade] = person_days
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parsed", type=Path, default=ROOT / "data/processed/parsed.jsonl")
    args = parser.parse_args()
    try:
        case = json.loads(GOLDEN.read_text(encoding="utf-8"))
        records = [json.loads(line) for line in args.parsed.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        result = check_case(records, case)
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: {case['id']} (고정 조건 노무량 환산만 검증)")
    for trade, days in result.items():
        print(f"  {trade}: {days} 인·일")
    print("실무자 검토 미완료. 단가·금액·할증·전체 견적은 검증하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

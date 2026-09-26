"""최소 에이전트(agent/flow/agent.py) 점검: 정상 사례와 누락·모호·범위 밖 입력.

실행: python evals/check_agent.py            # 계산 사례는 하이브리드 검색(질문마다 임베딩 1회)
      python evals/check_agent.py --offline  # 임베딩 없이 BM25만
단가는 계산 검증용 가상값이다(실제 노임단가 아님).
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import answer  # noqa: E402
from agent.tools.calc.unit_price import parse_rates
from agent.tools.calc.format import safe_console  # noqa: E402

SRC = "테스트용 가상값(실제 노임단가 아님)"
FULL = parse_rates({"rates": [
    {"trade": "콘크리트공", "unit_price": "1000", "basis_date": "2000-01-01", "source": SRC},
    {"trade": "보통인부", "unit_price": "2000", "basis_date": "2000-01-01", "source": SRC}]})
PART = parse_rates({"rates": [{"trade": "콘크리트공", "unit_price": "1000", "basis_date": "2000-01-01", "source": SRC}]})
NO_DATE = parse_rates({"rates": [
    {"trade": "콘크리트공", "unit_price": "1000", "basis_date": "", "source": SRC},
    {"trade": "보통인부", "unit_price": "2000", "basis_date": "2000-01-01", "source": SRC}]})
Q = "철근구조물 150㎥를 레미콘 인력운반 타설하면 노무비는 얼마야?"


class BrokenHybrid:
    """질문 처리 중 실패하는 하이브리드(키 없음·호출 한도 흉내)."""

    def __init__(self, bm25):
        self.bm25, self.chunks, self.api_calls = bm25, bm25.chunks, 0

    def search(self, query, k=5):
        raise RuntimeError("429 RESOURCE_EXHAUSTED (테스트)")


def items(resp):
    return {i["trade"]: i for i in resp["cost_items"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    safe_console()
    off = args.offline
    results = []

    def check(name, ok, resp=None):
        results.append(bool(ok))
        extra = f" [{resp['status']}]" if resp else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{extra}")

    # ---- 정상 사례 ----
    r = answer(Q, FULL, offline=off)
    it, text = items(r), r["final_response"]
    check("정상: 150㎥ → 각 22.5인·일", r["status"] == "OK" and all(i["person_days"] == "22.5" for i in it.values()), r)
    check("정상: 금액·합계 (Decimal 문자열)", it["콘크리트공"]["amount"] == "22500" and it["보통인부"]["amount"] == "45000"
          and r["total_cost"] == "67500", r)
    check("정상: 절·쪽·표·기준 표기 인용", all(s in text for s in ("6-1-1", "PDF 185쪽", "인쇄 129쪽", "p185-t0", "(일당)")), r)
    check("정상: 단가 기준일·출처 인용", "단가 기준일 2000-01-01" in text and SRC in text, r)
    expected_search = "bm25(오프라인 지정)" if off else "hybrid"
    check(f"정상: 검색 방식 {expected_search}, 임베딩 {0 if off else 1}회",
          r["search"]["method"] == expected_search and r["search"]["api_calls"] == (0 if off else 1)
          and "p185-t0" in r["search"]["top3"], r)
    check("정상: 공구손료 2%는 미적용으로 표시", "[미적용 조건]" in text and "인력품의 2%" in text, r)

    r = answer("철근콘크리트 구조물 1,250.5 m³ 인력 운반 타설 노무비", FULL, offline=off)
    it = items(r)
    check("정상: 쉼표·m³ 표기 물량 1,250.5 → 187.575인·일, 금액 정확",
          r["status"] == "OK" and it["콘크리트공"]["person_days"] == "187.575"
          and Decimal(it["보통인부"]["amount"]) == Decimal("375150"), r)

    # ---- 단가 부족: 금액을 만들지 않는다 ----
    r = answer(Q, {}, offline=off)
    check("단가 없음: 노무량은 산출, 금액 없음, 부족 항목 2개",
          r["status"] == "PARTIAL" and r["total_cost"] is None and all(i["amount"] is None for i in r["cost_items"])
          and len([m for m in r["missing_fields"] if m.startswith("노임단가")]) == 2
          and "노무비 합계: 미산정" in r["final_response"], r)
    r = answer(Q, PART, offline=off)
    check("단가 일부: 부분 합계와 미산정 직종 표시", r["status"] == "PARTIAL" and r["total_cost"] == "22500"
          and any("보통인부" in m for m in r["missing_fields"]) and "전체 노무비가 아닙니다" in r["final_response"], r)
    r = answer(Q, NO_DATE, offline=off)
    check("단가 기준일 없음: 그 직종은 미산정", items(r)["콘크리트공"]["amount"] is None
          and any("콘크리트공" in m and "기준일" in m for m in r["missing_fields"]), r)

    # ---- 누락·모호: 계산·검색하지 않는다 ----
    cases = [
        ("누락: 공법·구조물·물량 모두", "레미콘 타설 노무비 알려줘", 3, 0),
        ("누락: 물량", "철근구조물 레미콘 인력운반 타설 노무비", 1, 0),
        ("누락: 구조물", "레미콘 인력운반 타설 200㎥ 노무비", 1, 0),
        ("모호: 물량 두 개", "철근구조물 100㎥ 또는 120㎥ 인력운반 타설 노무비", 0, 1),
        ("모호: 철근·무근 함께", "철근구조물과 무근구조물 100㎥ 인력운반 타설", 0, 1),
        ("모호: 단위 없는 숫자", "철근구조물 인력운반 타설 100 노무비", 0, 1),
        ("모호: ㎥ 아닌 단위", "철근구조물 인력운반 타설 100㎡ 노무비", 0, 1),
        ("모호: 0㎥", "철근구조물 0㎥ 인력운반 타설", 0, 1),
        ("모호: 음수 물량", "철근구조물 -5㎥ 인력운반 타설", 0, 1),
        ("모호: '철근'만", "철근 100㎥ 인력운반 타설 노무비", 0, 1),
        ("모호: 인력운반·장비사용 함께", "철근구조물 100㎥ 인력운반 또는 장비사용 타설", 0, 1),
    ]
    for name, query, n_missing, n_ambiguous in cases:
        r = answer(query, FULL, offline=off)
        ok = (r["status"] == "MISSING_INFO" and len(r["missing_fields"]) == n_missing
              and len(r["ambiguities"]) == n_ambiguous and r["search"] is None and r["total_cost"] is None
              and not r["cost_items"] and "추정값을 넣지 않았습니다" in r["final_response"])
        check(f"{name} (검색·API 없음)", ok, r)

    # ---- 지원 범위 밖 ----
    for name, query in [("범위 밖: 장비사용 타설", "철근구조물 100㎥ 장비사용 타설 노무비"),
                        ("범위 밖: 무근구조물", "무근구조물 100㎥ 인력운반 타설 노무비"),
                        ("범위 밖: 펌프차 타설", "콘크리트 펌프차 타설 철근구조물 100㎥"),
                        ("범위 밖: 다른 절 번호", "6-1-4 타설 노무비"),
                        ("범위 밖: PC기둥", "PC기둥 설치 노무비"),
                        ("범위 밖: 무관한 질문", "오늘 현장 날씨 어때?")]:
        r = answer(query, FULL, offline=off)
        check(name, r["status"] == "OUT_OF_SCOPE" and r["total_cost"] is None and r["search"] is None, r)

    # ---- 검색 실패 대체 ----
    def failing_factory(bm25):
        raise ImportError("google-genai 없음 (테스트)")

    r = answer(Q, FULL, hybrid_factory=failing_factory)
    check("하이브리드 준비 실패 → BM25 대체·경고, 결과 유지", r["status"] == "OK" and r["search"]["method"] == "bm25(대체)"
          and r["warnings"] and r["total_cost"] == "67500", r)
    r = answer(Q, FULL, hybrid_factory=BrokenHybrid)
    check("하이브리드 질의 중 실패 → BM25 대체·경고, 결과 유지", r["status"] == "OK" and r["search"]["method"] == "bm25(대체)"
          and any("429" in w for w in r["warnings"]) and r["total_cost"] == "67500", r)

    # ---- 정확값 필드와 금액 표시 정책(미정) ----
    r = answer(Q, FULL, offline=True)
    it = items(r)
    check("정확값 필드 추가, 기존 값 유지(22.5·22500·67500), 표시·적용 금액 정책 미정",
          it["콘크리트공"]["person_days_exact"] == "22.5" and it["콘크리트공"]["amount_exact"] == "22500"
          and it["콘크리트공"]["amount"] == "22500" and r["total_cost_exact"] == "67500" and r["total_cost"] == "67500"
          and r["amount_policy"]["display_and_applied_amount"] == "미정"
          and it["콘크리트공"]["applied_amount"] == {"value": None, "policy": "미정"}
          and "[금액 표시]" in r["final_response"], r)
    r = answer(Q, {}, offline=True)
    check("단가 없음: 정확한 노무량(22.5)은 반환, 금액 정확값 없음", all(i["person_days_exact"] == "22.5"
          and i["amount_exact"] is None for i in r["cost_items"]) and "[금액 표시]" not in r["final_response"], r)

    # ---- 품량 단계 연결: 에이전트의 노무량은 calc/quantity.py에서 온다 ----
    from agent.nodes import quantity as quantity_node
    from agent.tools.calc import legacy_labor as rag

    calls, original = [], quantity_node.compute

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("에이전트 경로에서 옛 rag.estimate_labor를 호출했다")

    old_estimate = rag.estimate_labor
    quantity_node.compute, rag.estimate_labor = spy, forbidden
    try:
        r = answer(Q, FULL, offline=True)
    finally:
        quantity_node.compute, rag.estimate_labor = original, old_estimate
    check("품량 연결: quantity_step이 quantity.compute를 1회 호출(6-1-1, 공법·구조물·물량 전달)",
          calls == [("6-1-1", {"공법": "인력운반 타설", "구조물": "철근구조물"}, "150")], r)
    check("품량 연결: 옛 rag.estimate_labor 없이 같은 결과(각 22.5, 합계 67500)", r["status"] == "OK"
          and all(i["person_days"] == "22.5" for i in r["cost_items"]) and r["total_cost"] == "67500", r)

    def refused(*args, **kwargs):
        return {"status": "refused", "reason": "테스트: 계산기가 거부함", "lines": []}

    quantity_node.compute = refused
    try:
        r = answer(Q, FULL, offline=True)
    finally:
        quantity_node.compute = original
    check("품량 계산기가 거부하면 금액 없이 ERROR", r["status"] == "ERROR" and r["total_cost"] is None
          and not r["cost_items"] and "계산기가 거부함" in r["summary"], r)

    print(f"\n통과 {sum(results)} / 전체 {len(results)} (가상 단가로 흐름만 검증. 실제 금액 아님)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

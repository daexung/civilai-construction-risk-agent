"""최소 에이전트: 6-1-1 '철근구조물 인력운반 타설' 한 사례의 노무량·노무비 질의응답.

실행 예:
    python -m agent "철근구조물 150㎥ 레미콘 인력운반 타설 노무비는?" --rates 내_노임단가.json
    python -m agent "레미콘 타설 노무비 알려줘"            # 조건 부족 → 필요한 항목 안내
    python -m agent "…" --offline                            # 임베딩 없이 BM25만

흐름 (v1.0-team의 router → extractor → 비용 노드 → synthesize 구조와 결과 형식을 참고했다.
      지원 범위가 한 사례라 LLM 없이 규칙으로 판정한다)
  route     질문이 지원 사례를 묻는지 판정한다. 다른 공종·공법·구조물이면 OUT_OF_SCOPE
  extract   공법·구조물·물량을 뽑고 검증한다. 없으면 missing_fields, 여럿이거나 불분명하면 ambiguities
            → 하나라도 있으면 계산하지 않고 MISSING_INFO로 되묻는다(검색·API 호출도 하지 않는다)
  retrieve  하이브리드 검색(BM25 + 벡터 RRF)으로 품셈 근거를 찾는다. 임베딩을 쓸 수 없으면 BM25로 대신하고 기록한다
  quantity  nodes.quantity.quantity_step → tools/calc/quantity.py (원문 표 품량, 유리수 정확 계산). 거부되면 ERROR
  price     unit_price.apply_prices (단가 적용). 계산에 쓴 원문 표가 검색 근거에 없으면 답하지 않는다(ERROR)
  respond   절·쪽·표 위치와 단가 기준일·출처를 붙여 답한다. 단가가 없는 직종은 금액을 만들지 않고 부족 항목으로 알린다
"""

import argparse
import json
import sys
from pathlib import Path

from agent.graph import answer
from agent.tools.calc.unit_price import RateError, load_rates
from agent.tools.calc.format import safe_console, to_json

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

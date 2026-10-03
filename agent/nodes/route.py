"""공사비·품셈 계산 질문인지 단서 낱말로만 판단한다.
공종과 계산 가능 여부는 여기서 판단하지 않는다.
"""

import unicodedata
import re

from agent.state import AgentState


COST_TERMS = (
    "노무비", "인건비", "공사비", "견적", "품셈", "일위대가", "단가", "품량", "타설",
    "비용", "금액", "얼마", "인력", "인원", "공수", "품", "설치", "해체", "시공",
    "개소", "톤", "ton", "kg", "km", "루베",
)

QUANTITY_UNIT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:m3|m2|m|km|t|ton|kg|개소|개|본|대|층|톤)(?![a-z])", re.I)


def route(state: AgentState) -> dict:
    query = unicodedata.normalize("NFKC", state["query"])
    if not any(term in query for term in COST_TERMS) and not QUANTITY_UNIT.search(query):
        return {"status": "OUT_OF_SCOPE", "reason": "공사비·품셈 계산 질문이 아닙니다"}
    return {}

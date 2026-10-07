"""질문을 견적·품셈 상담·범위 밖으로 나누는 공통 규칙(LLM 없이 쓰는 분류).

route가 LLM을 쓰지 않거나 LLM 호출이 실패했을 때 이 분류를 쓴다. split·select 같은 뒤 노드는
질문 의도를 다시 판단하지 않고 route의 최종 결과(state["route"])만 따른다.

판단 원칙은 LLM 분류 프롬프트(tools/llm/prompts/router.md)의 창구 정의와 같다.
- 돈(비용·견적·공사비·노무비 등)을 실제로 구하면 견적이다. 문장 어미(되나요·주세요 등)는 보지 않는다.
- 돈을 말해도 물량 없이 산정 방법·기준만 물으면 상담이다("노무비는 어떤 방식으로 산정해?").
- 돈을 묻지 않고 품·인원·시간·할증·시공량·포함 여부 같은 품셈 기준을 물으면 상담이다.
- 다시 계산해 달라는 요청은 견적이다.
- 그 밖에는 기존 낱말 규칙을 그대로 쓴다(품셈 낱말·물량이 있으면 견적, 없으면 범위 밖).
"""

from __future__ import annotations

import re
import unicodedata

COST_TERMS = (
    "노무비", "인건비", "공사비", "견적", "예산", "일위대가", "단가", "물량", "대가",
    "비용", "금액", "얼마", "인력", "인원", "공수", "품", "설치", "해체", "시공",
    "개소", "㎡", "ton", "kg", "km", "루베",
)
QUANTITY_UNIT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:m3|m2|m|km|t|ton|kg|개소|개|평|㎡|㎥)(?![a-z])", re.I)

# 돈을 구하는 낱말(router.md의 estimate 정의).
_MONEY = re.compile(r"비용|금액|견적|공사비|인건비|노무비|원가|도급액")
# 산정 방법·기준을 묻는 말.
_METHOD = re.compile(r"어떻게|어떤\s*(?:방식|기준|방법)|방식으로|방법|기준이\s*뭐")
# 돈이 아닌 품셈 기준을 묻는 말(router.md의 qa 정의: 품·인원·시간·기준·할증·적용 방법).
_RULE_TOPIC = re.compile(r"품(?:이|은|을|의|에|도|만)?(?:\s|$|\?|이랑)|인원|몇\s*(?:명|인|%|퍼센트)|퍼센트|할증|가산|감산"
                         r"|손율|시공량|작업능력|시간은|포함돼|포함되|별도\s*(?:계상|산정)|계수|적용해")
# 다시 계산해 달라는 요청.
_RECALCULATE = re.compile(r"다시\s*(?:계산|해|뽑)|재계산")
# router.md에서 범위 밖으로 정의한 주제(평당 공사비·자재 시세·도면 물량 산출).
_OUT_TOPIC = re.compile(r"평당|시세|도면")


def _legacy(normalized: str) -> str:
    """main의 기존 낱말 규칙."""
    return "estimate" if any(term in normalized for term in COST_TERMS) or QUANTITY_UNIT.search(normalized) else "out_of_scope"


def classify(query: str) -> str:
    """'estimate' / 'qa' / 'out_of_scope'."""
    text = unicodedata.normalize("NFKC", query)
    legacy = _legacy(text)
    if _OUT_TOPIC.search(text):
        return "out_of_scope"
    quantity = bool(QUANTITY_UNIT.search(text))
    if _MONEY.search(text):
        return "qa" if _METHOD.search(text) and not quantity else "estimate"
    if _RULE_TOPIC.search(text) or (_METHOD.search(text) and legacy == "estimate"):
        return "qa"
    if _RECALCULATE.search(text):
        return "estimate"
    return legacy

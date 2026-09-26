"""Extract method, structure, and volume without guessing."""

import re
import unicodedata

from agent.rules.section_6 import SUPPORTED_CASE
from agent.tools.calc.inputs import VolumeError, parse_volume

MANUAL_RE = re.compile(r"인력\s*운반|손수레")
EQUIPMENT_RE = re.compile(r"장비\s*사용|굴착기")
REINFORCED_RE = re.compile(r"철근\s*(?:콘크리트\s*)?구조물|철근\s*콘크리트|RC\s*구조")
PLAIN_RE = re.compile(r"무근")
# NFKC로 ㎥·m³ → m3 로 맞춘 뒤 찾는다
VOLUME_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(?:m3|세제곱\s*미터|입방\s*미터|루베)")
OTHER_UNIT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(m2|평|톤|ton|t\b|kg|개소|개|m(?!3))")
BARE_NUMBER_RE = re.compile(r"(?<![\w.,-])(\d[\d,]*(?:\.\d+)?)(?![\d,.]*\s*(?:m\d?|세제곱|입방|루베|평|톤|ton|t\b|kg|개|%|인|일|년|월))")

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



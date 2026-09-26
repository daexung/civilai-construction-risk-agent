"""Supported question routing."""

import re
import unicodedata

# 지원 사례를 묻는 질문인지: 레미콘 타설 관련 낱말 중 하나는 있어야 한다
DOMAIN_TERMS = ("레미콘", "레디믹스트", "콘크리트 타설", "콘크리트타설", "타설", "6-1-1")
# 다른 절·공종을 가리키는 낱말. 있으면 이번 범위 밖이다
OTHER_WORK = {"펌프": "콘크리트 펌프차 타설(6-1-4)", "현장비빔": "현장비빔타설(6-1-2)", "비빔": "현장비빔타설(6-1-2)",
              "거푸집": "거푸집(6-3)", "철근가공": "철근 가공(6-2)", "철근 가공": "철근 가공(6-2)",
              "철근조립": "철근 조립(6-2)", "철근 조립": "철근 조립(6-2)", "표면 마무리": "표면 마무리(6-1-3)",
              "PC": "조립식 구조물(6-7)", "PSC": "포스트텐션(6-4)"}
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


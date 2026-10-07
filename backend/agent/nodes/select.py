"""검색 순위로 작업 절을 고른다."""

import json
import re
import unicodedata
from functools import cache
from pathlib import Path

from backend.agent.nodes.fill import _norm
from backend.paths import ROOT
from backend.agent.rules.specs import specs_by_section
from backend.agent.state import AgentState


# check_select.py 하이브리드 34문항: 4.0은 오답 0·되묻기 20, 3.0은 오답 2.
MARGIN = 4.0
RARE_SHARE = 0.05
NOT_FOUND = ("질문에 맞는 품셈 공종을 찾지 못했어요. 공종 이름과 작업 방법을 함께 알려 주세요"
             "(예: 레미콘 펌프차 타설, 합판거푸집 설치).")
# 공종을 가리키지 않는 낱말. 이 낱말만으로는 절 제목과의 관련을 판단하지 않는다.
_STOP = {"견적", "비용", "공사비", "공사", "금액", "얼마", "물량", "부탁", "계산", "인건비", "노무비", "작업",
         "현장", "정도", "이번", "필요", "관련", "기준", "경우", "공종", "품셈", "개소", "루베", "주세요",
         "드려요", "해줘", "해주세요", "알려", "뽑아", "계산해줘", "다시", "아까", "하려면", "하면", "할때", "얼마나", "나올까요", "인가요"}
_PARTICLE = re.compile(r"(?:은|는|이|가|을|를|도|로|으로|의|에|와|과|랑|만)$")
# 관련성 검사는 견적 요청에만 쓴다. 공종 이름 없이 묻는 품셈 규칙 질문은 기존 판정을 따른다.
_QUANTITY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:㎥|㎡|m3|m2|루베|개소|ton|톤|km|kg|m|t|본|개(?!월))(?![a-z])", re.I)
_COST_REQUEST = re.compile(r"견적|비용|얼마|공사비|금액|인건비|노무비")
_RULE_QUESTION = re.compile(r"어떻게|하나요|되나요|습니까|있나요|는지")


def _estimate_request(query: str) -> bool:
    return bool(_QUANTITY.search(query) or _COST_REQUEST.search(query)) and not _RULE_QUESTION.search(query)


@cache
def _card_aliases() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """카드에 적힌 공종 별칭(레미콘 → 레디믹스트콘크리트 타설)."""
    cards = []
    for path in sorted((Path(__file__).resolve().parents[1] / "rules/cards").glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        cards.append((_norm(card["title"]), tuple(_norm(alias) for alias in card.get("aliases", []))))
    return tuple(cards)


@cache
def _section_texts() -> dict[tuple[str, str], str]:
    """절별 원문(공백 제거). 원문 검색 파일이 없으면 빈 사전이고 제목·별칭만으로 판단한다."""
    texts: dict[tuple[str, str], list[str]] = {}
    try:
        with (ROOT / "data/processed/chunks.all.jsonl").open(encoding="utf-8") as lines:
            for line in lines:
                chunk = json.loads(line)
                texts.setdefault((chunk.get("division", "공통"), chunk["section_no"]), []).append(chunk["text"])
    except OSError:
        return {}
    return {key: _norm(" ".join(parts)) for key, parts in texts.items()}


@cache
def _rare(word: str) -> bool:
    """전체 절의 3% 이하에만 나오는 낱말. '콘크리트'처럼 흔한 낱말은 원문 일치만으로 관련을 인정하지 않는다."""
    texts = _section_texts()
    return bool(texts) and sum(word in text for text in texts.values()) <= len(texts) * RARE_SHARE


def _words(query: str) -> set[str]:
    words = {_PARTICLE.sub("", word) for word in re.findall(r"[가-힣A-Za-z]{2,}", unicodedata.normalize("NFKC", query))}
    return {_norm(word) for word in words if len(word) >= 2 and word not in _STOP}


def _relevant(group: dict, words: set[str]) -> bool:
    """질문의 내용어가 절 제목·카드 별칭에 있거나, 드문 낱말이 그 절 원문에 있으면 관련 후보로 본다."""
    title = _norm(re.sub(r"\(.*?\)", "", group["section"]))
    names = [title, *(alias for card, aliases in _card_aliases() if card in title for alias in aliases)]
    # 끝 한 글자는 어미일 수 있다(바탕처리할 → 바탕처리).
    stems = words | {word[:-1] for word in words if len(word) >= 3}
    if any(stem in name for stem in stems for name in names):
        return True
    text = _section_texts().get((group["division"], group["section_no"]), "")
    # 두 글자 낱말(부을·대충)은 구어가 많아 원문 일치 근거로 쓰지 않는다.
    return any(len(word) >= 3 and word in text and _rare(word) for word in words)


def decide(hits: list[dict], specs: dict[tuple[str, str], list[dict]], margin: float = MARGIN,
           query: str | None = None) -> dict:
    """청크 순위와 명세 목록으로 결정·후보·이유를 돌려준다.

    query를 주면 질문과 관련 없는 절을 확정하지 않는다. 검색 1위가 질문의 공종 낱말과 맞지 않으면
    상위 6개 절 가운데 관련 있는 절만 후보로 되묻고, 관련 절이 없으면 not_found를 돌려준다.
    """
    by_section: dict[tuple[str | None, str], dict] = {}
    for hit in hits:
        section_no = hit.get("section_no")
        if not section_no or section_no.count("-") != 2:
            continue
        division = hit.get("division", "공통")  # Old saved 6장 hits predate this field.
        key = (division, section_no)
        group = by_section.setdefault(key, {
            "division": division, "section_no": section_no,
            "section": (f"{division} {section_no} {specs[key][0]['title']}" if specs.get(key)
                        else f"{division} {hit['section']}" if division else hit["section"]),
            "score": 0.0, "has_spec": bool(specs.get(key)),
        })
        group["score"] += 1 / hit["rank"]

    ranked = sorted(by_section.values(), key=lambda group: (-group["score"],
                    group["division"] or "", group["section_no"]))
    candidates = ranked[:3]
    if not candidates:
        if query:  # 견적 요청인데 고를 후보가 없으면 빈 선택지로 묻지 않고 찾지 못했다고 안내한다
            return {"decision": "not_found", "confirmed": False, "candidates": [], "reason": NOT_FOUND}
        return {"decision": "ask", "candidates": [], "reason": "작업 절을 찾지 못했습니다"}

    words = _words(query) if query else set()
    shown = candidates
    if query and not words:  # 견적 요청인데 공종을 가리키는 낱말이 없다("아까 거 100㎥")
        return {"decision": "not_found", "confirmed": False, "candidates": [], "reason": NOT_FOUND}
    if words:
        if not _relevant(candidates[0], words):
            # 검색 1위가 질문의 공종과 맞지 않으면 확정하지 않는다. 관련 후보 순서:
            # 검색 상위 6개 중 계산 명세가 있는 관련 절 → 제목·카드 별칭이 질문 낱말과 맞는 명세 절
            # (카드에 별칭이 정리된 절 먼저) → 명세 없는 관련 절. 하나도 없으면 찾지 못했다고 안내한다.
            hits_relevant = [group for group in ranked[:6] if _relevant(group, words)]
            carded = {title for title, _ in _card_aliases()}
            catalog = [{"division": division, "section_no": section_no, "score": 0.0, "has_spec": True,
                        "section": f"{division} {section_no} {entries[0]['title']}"}
                       for (division, section_no), entries in sorted(specs.items())
                       if (division, section_no) not in by_section]
            catalog = sorted((group for group in catalog if _relevant(group, words)),
                             key=lambda group: not any(title in _norm(group["section"]) for title in carded))
            relevant = ([group for group in hits_relevant if group["has_spec"]] + catalog
                        + [group for group in hits_relevant if not group["has_spec"]])
            if not relevant:
                return {"decision": "not_found", "confirmed": False, "candidates": [], "reason": NOT_FOUND}
            # 어느 후보도 확신할 수 없으므로 명세를 미리 고르지 않고 공종부터 묻는다.
            return {"decision": "provisional", "confirmed": False, "candidates": relevant[:3],
                    "reason": f"검색 1위 {candidates[0]['section']}은(는) 질문의 공종과 맞지 않아 관련 후보를 확인합니다",
                    "spec_id": ""}
        # 판정은 기존 점수 비교 그대로, 되물을 때 보여 줄 후보에서만 관련 없는 절을 뺀다.
        shown = [group for group in candidates if _relevant(group, words)]

    first = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if second and first["score"] < margin * second["score"]:
        return {"decision": "provisional", "confirmed": False, "candidates": shown,
                "reason": f"상위 절 {first['section']}와 {second['section']}의 검색 점수가 비슷합니다",
                "spec_id": specs[(first["division"], first["section_no"])][0]["id"] if first["has_spec"] else ""}
    if not first["has_spec"]:
        return {"decision": "no_spec", "confirmed": True, "candidates": shown,
                "reason": f"{first['section']} 절의 계산 명세가 없습니다"}
    return {"decision": "chosen", "confirmed": True, "candidates": shown,
            "reason": f"{first['section']} 절의 검색 점수가 가장 높습니다",
            "spec_id": specs[(first["division"], first["section_no"])][0]["id"]}


def select(state: AgentState) -> dict:
    query = state.get("query") or ""
    result = decide(state["hits"], specs_by_section(), query=query if _estimate_request(query) else None)
    decision = result["decision"]
    update = {"candidates": result["candidates"],
              "selection": {"decision": decision, "confirmed": result.get("confirmed", False),
                            "reason": result["reason"]}}
    if decision in ("chosen", "provisional"):
        update["spec_id"] = result["spec_id"]
    elif decision == "ask":
        names = ", ".join(item["section"] for item in result["candidates"])
        update.update(status="MISSING_INFO", reason=f"어느 공종인지 알려 주세요: {names}" if names else result["reason"])
    elif decision == "not_found":
        # 관련 없는 근거를 보여 주지 않는다.
        update.update(status="EVIDENCE_ONLY", reason=result["reason"], hits=[])
    else:
        update.update(status="EVIDENCE_ONLY", reason=result["reason"])
    return update

"""검색 순위로 작업 절을 고른다."""

import re

from backend.agent.rules.specs import specs_by_section
from backend.agent.state import AgentState


# check_select.py 하이브리드 34문항: 4.0은 오답 0·되묻기 20, 3.0은 오답 2.
MARGIN = 4.0


_METHODS = ("롤러칠", "붓칠", "뿜칠")
_NEGATED = re.compile(r"(?:말고|아니(?:고|면|라)|제외하고|대신|또는|혹은|아니면|말자)")


def _explicit_candidate(query: str, candidates: list[dict], specs: dict) -> dict | None:
    """명시된 공종명과 구별 작업방식이 후보 하나와 맞을 때만 우선한다."""
    methods = [method for method in _METHODS if method in query]
    if len(methods) != 1 or _NEGATED.search(query):
        return None
    method = methods[0]
    named_trades = [term for term in ("수성페인트", "유성페인트") if term in query]
    if len(named_trades) > 1:
        return None
    requested_trade = next((term for term in ("수성페인트", "유성페인트", "페인트", "도장") if term in query), None)
    # "페인트"처럼 수성·유성을 구별하지 않은 요청은 후보 순위만으로 확정하지 않는다.
    if requested_trade not in ("수성페인트", "유성페인트"):
        return None
    all_named = {division for (division, _), entries in specs.items()
                 if any(method in " ".join((entry.get("title", ""), entry.get("work", "")))
                        and (not requested_trade or requested_trade in " ".join((entry.get("title", ""), entry.get("work", ""))))
                        for entry in entries)}
    if len(all_named) > 1:
        return None
    # 다른 부문에 같은 이름의 공종이 있으면 질문으로 남긴다.
    method_candidates = []
    for candidate in candidates:
        entries = specs.get((candidate["division"], candidate["section_no"]), [])
        text = " ".join([candidate.get("section", ""), *(s.get("title", "") for s in entries),
                         *(s.get("work", "") for s in entries)])
        if method in text and requested_trade and requested_trade in text:
            method_candidates.append(candidate)
    if len(method_candidates) != 1:
        return None
    return method_candidates[0]


def decide(hits: list[dict], specs: dict[tuple[str, str], list[dict]], margin: float = MARGIN,
           query: str = "") -> dict:
    """청크 순위와 명세 목록으로 결정·후보·이유를 돌려준다."""
    by_section: dict[tuple[str | None, str], dict] = {}
    best_scores = {}
    for hit in hits:
        section_no = hit.get("section_no")
        if not section_no:
            continue
        division = hit.get("division", "공통")  # Old saved 6장 hits predate this field.
        key = (division, section_no)
        # Most estimate sections use a three-part number. Machine items (for
        # example 2104-0010) and source catalog entries (2402) use other exact
        # identifiers; accept those only when an executable spec exists.
        if section_no.count("-") != 2 and not specs.get(key):
            continue
        group = by_section.setdefault(key, {
            "division": division, "section_no": section_no,
            "section": (f"{division} {section_no} {specs[key][0]['title']}" if specs.get(key)
                        else f"{division} {hit['section']}" if division else hit["section"]),
            "score": 0.0, "has_spec": bool(specs.get(key)),
            "spec_id": specs[key][0]["id"] if specs.get(key) else "",
        })
        group["score"] += 1 / hit["rank"]
        best_scores[key] = max(best_scores.get(key, 0.0), 1 / hit["rank"])

    candidates = sorted(by_section.values(), key=lambda group: (-group["score"],
                        group["division"] or "", group["section_no"]))[:3]
    if not candidates:
        return {"decision": "ask", "candidates": [], "reason": "작업 절을 찾지 못했습니다"}

    first = candidates[0]
    explicit = _explicit_candidate(query, candidates, specs) if query else None
    if explicit and explicit["has_spec"]:
        spec = specs[(explicit["division"], explicit["section_no"])][0]
        return {"decision": "chosen", "confirmed": True, "candidates": candidates,
                "reason": f"요청의 공종명과 작업 방식({next(m for m in _METHODS if m in query)})이 일치합니다",
                "spec_id": spec["id"], "selected": explicit, "selection_source": "explicit_name_and_method"}
    mentioned_methods = [method for method in _METHODS if method in query]
    paint_request = any(term in query for term in ("수성페인트", "유성페인트", "페인트"))
    paint_candidate = any(any(method in " ".join((candidate.get("section", ""),
                                                  *(spec.get("title", "") for spec in specs.get(
                                                      (candidate["division"], candidate["section_no"]), []))))
                               for method in _METHODS) for candidate in candidates)
    if mentioned_methods or (paint_request and not mentioned_methods and paint_candidate):
        ranked_by_hit = sorted(by_section.values(), key=lambda group: (
            -best_scores[(group["division"], group["section_no"])],
            group["division"] or "", group["section_no"]))[:3]
        provisional_first = ranked_by_hit[0]
        reason = ("공종명과 작업 방식 후보가 일치하지 않거나 여러 방식이 언급되어 확인이 필요합니다"
                  if mentioned_methods else "도장 방식이 지정되지 않아 확인이 필요합니다")
        return {"decision": "provisional", "confirmed": False, "candidates": ranked_by_hit,
                "reason": reason,
                "spec_id": (specs[(provisional_first["division"], provisional_first["section_no"])][0]["id"]
                            if provisional_first["has_spec"] else "")}
    second = candidates[1] if len(candidates) > 1 else None
    if second and first["score"] < margin * second["score"]:
        candidates = sorted(by_section.values(), key=lambda group: (
            -best_scores[(group["division"], group["section_no"])],
            group["division"] or "", group["section_no"]))[:3]
        provisional_first = candidates[0]
        return {"decision": "provisional", "confirmed": False, "candidates": candidates,
                "reason": f"상위 절 {first['section']}와 {second['section']}의 검색 점수가 비슷합니다",
                "spec_id": specs[(provisional_first["division"], provisional_first["section_no"])][0]["id"] if provisional_first["has_spec"] else ""}
    if not first["has_spec"]:
        return {"decision": "no_spec", "confirmed": True, "candidates": candidates,
                "reason": f"{first['section']} 절의 계산 명세가 없습니다"}
    return {"decision": "chosen", "confirmed": True, "candidates": candidates,
            "reason": f"{first['section']} 절의 검색 점수가 가장 높습니다",
            "spec_id": specs[(first["division"], first["section_no"])][0]["id"]}


def select(state: AgentState) -> dict:
    result = decide(state["hits"], specs_by_section(), query=state.get("query", ""))
    decision = result["decision"]
    update = {"candidates": result["candidates"],
              "selection": {"decision": decision, "confirmed": result.get("confirmed", False),
                            "reason": result["reason"], "source": result.get("selection_source", "search_score"),
                            "spec_id": result.get("spec_id"),
                            "section_no": (result.get("selected") or {}).get("section_no")}}
    if decision in ("chosen", "provisional"):
        update["spec_id"] = result["spec_id"]
    elif decision == "ask":
        names = ", ".join(item["section"] for item in result["candidates"])
        update.update(status="MISSING_INFO", reason=f"어느 공종인지 알려 주세요: {names}" if names else result["reason"])
    else:
        update.update(status="EVIDENCE_ONLY", reason=result["reason"])
    return update

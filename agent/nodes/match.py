"""절 번호, 알려진 다른 공종, 카드 aliases 순서로 질문을 판정한다.
카드가 여러 장이면 되묻고, 한 장이면 그 id만 돌려준다.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from agent.rules.cards import load_cards
from agent.state import AgentState


OTHER_WORK_FILE = Path(__file__).resolve().parents[1] / "rules/other_work.json"
SECTION_RE = re.compile(r"\d+-\d+(?:-\d+)?")


def _compact(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, dict], list[dict]]:
    cards = load_cards()
    other_work = json.loads(OTHER_WORK_FILE.read_text(encoding="utf-8"))
    return cards, other_work


def match(state: AgentState) -> dict:
    cards, other_work = _catalog()
    query = _compact(state["query"])

    unknown = [section for section in dict.fromkeys(SECTION_RE.findall(query)) if section not in cards]
    if unknown:
        return {"status": "OUT_OF_SCOPE", "reason": f"지원하지 않는 절입니다: {', '.join(unknown)}"}

    others = sorted({item["name"] for item in other_work if _compact(item["term"]) in query})
    if others:
        return {"status": "OUT_OF_SCOPE", "reason": f"지원하지 않는 공종·공법입니다: {', '.join(others)}"}

    candidates = sorted(card_id for card_id, card in cards.items()
                        if any(_compact(alias) in query for alias in card["aliases"]))
    if not candidates:
        return {"status": "OUT_OF_SCOPE", "reason": "지원하는 공종 카드에 해당하지 않습니다"}
    if len(candidates) > 1:
        names = ", ".join(f"{card_id} {cards[card_id]['title']}" for card_id in candidates)
        return {"status": "MISSING_INFO", "reason": f"어느 공종인지 알려 주세요: {names}",
                "candidates": candidates}
    return {"card_id": candidates[0]}

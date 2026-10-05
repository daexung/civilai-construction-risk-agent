"""공종 카드 JSON을 읽고 입력 조건의 참조를 검사한다."""

import json
from pathlib import Path


CARDS_DIR = Path(__file__).with_name("cards")
REQUIRED = {
    "id", "title", "section", "source", "aliases", "basis", "inputs",
    "confirmations", "verified", "trades", "assumptions", "not_calculated",
}


def _invalid(path: Path, reason: str) -> None:
    raise ValueError(f"{path.name}: {reason}")


def _conditions(path: Path, label: str, conditions: object, choices: dict[str, set[str]],
                allow_empty: bool = False) -> None:
    if not isinstance(conditions, dict) or (not conditions and not allow_empty):
        _invalid(path, f"{label}의 조건이 비어 있거나 객체가 아닙니다")
    for name, value in conditions.items():
        if not isinstance(name, str) or name not in choices:
            _invalid(path, f"{label}의 알 수 없는 condition: {name}")
        if not isinstance(value, str) or value not in choices[name]:
            _invalid(path, f"{label}의 {name}에 없는 값: {value}")


def _validate(path: Path, card: object) -> None:
    if not isinstance(card, dict):
        _invalid(path, "카드는 JSON 객체여야 합니다")
    missing = REQUIRED - card.keys()
    if missing:
        _invalid(path, f"필수 키 누락: {', '.join(sorted(missing))}")
    if card["id"] != path.stem:
        _invalid(path, f"파일 이름과 id 불일치: {card['id']!r}")
    for name in ("title", "section", "basis"):
        if not isinstance(card[name], str) or not card[name]:
            _invalid(path, f"{name}은 빈 문자열일 수 없습니다")
    for name in ("aliases", "trades", "assumptions", "not_calculated"):
        if not isinstance(card[name], list) or any(not isinstance(v, str) or not v for v in card[name]):
            _invalid(path, f"{name}은 문자열 목록이어야 합니다")
    if not isinstance(card["source"], dict) or not {"pdf_page", "printed_page", "table_id"} <= card["source"].keys():
        _invalid(path, "source에 pdf_page, printed_page, table_id가 필요합니다")
    if not isinstance(card["inputs"], list):
        _invalid(path, "inputs는 목록이어야 합니다")

    keys: set[str] = set()
    choices: dict[str, set[str]] = {}
    for number, item in enumerate(card["inputs"], 1):
        label = f"inputs[{number}]"
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"] or not isinstance(item.get("ask"), str) or not item["ask"]:
            _invalid(path, f"{label}에 key와 ask가 필요합니다")
        if item["key"] in keys:
            _invalid(path, f"{label}의 중복 key: {item['key']}")
        keys.add(item["key"])
        if item.get("type") == "quantity":
            if not isinstance(item.get("unit"), str) or not item["unit"]:
                _invalid(path, f"{label} 물량형에 unit이 필요합니다")
        else:
            if not isinstance(item.get("condition"), str) or not item["condition"] or not isinstance(item.get("values"), dict) or not item["values"]:
                _invalid(path, f"{label} 선택형에 condition과 values가 필요합니다")
            if any(not isinstance(v, list) or any(not isinstance(s, str) or not s for s in v)
                   for v in item["values"].values()):
                _invalid(path, f"{label}의 values는 정식 값별 동의어 목록이어야 합니다")
            if item["condition"] in choices:
                _invalid(path, f"{label}의 중복 condition: {item['condition']}")
            choices[item["condition"]] = set(item["values"])

    if not isinstance(card["verified"], list):
        _invalid(path, "verified는 목록이어야 합니다")
    for number, item in enumerate(card["verified"], 1):
        label = f"verified[{number}]"
        if not isinstance(item, dict):
            _invalid(path, f"{label}는 객체여야 합니다")
        _conditions(path, label, item.get("conditions"), choices, allow_empty=not choices)
        if set(item["conditions"]) != set(choices):
            _invalid(path, f"{label}에 모든 선택 조건이 필요합니다")

    if not isinstance(card["confirmations"], list):
        _invalid(path, "confirmations는 목록이어야 합니다")
    for number, item in enumerate(card["confirmations"], 1):
        label = f"confirmations[{number}]"
        if not isinstance(item, dict) or not all(item.get(k) for k in ("key", "question", "clause_marker")):
            _invalid(path, f"{label}에 key, question, clause_marker가 필요합니다")
        _conditions(path, label, item.get("when"), choices)


def load_cards() -> dict[str, dict]:
    cards = {}
    for path in sorted(CARDS_DIR.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _invalid(path, f"JSON을 읽을 수 없습니다: {exc}")
        _validate(path, card)
        cards[card["id"]] = card
    return cards

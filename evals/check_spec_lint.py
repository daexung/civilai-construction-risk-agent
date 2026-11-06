"""운영에 들어가는 계산 명세(카드)의 문법 검사. 표준 라이브러리만 쓰고 외부 호출이 없다.

계산기는 이름과 값을 글자 그대로 비교한다. 그래서 이름이 조금만 어긋나도 오류 없이 규칙이 빠진다
(예: 할증 대상 '????'·작업 이름 → 할증이 붙지 않음). 이런 '조용히 안 맞는' 경우를 잡는다.

검사:
- 깨진 글자: 한글이 '?'로 바뀐 문자열.
- 할증 대상: surcharges[].applies_to 이름이 카드의 직종·장비 이름과 똑같은지(adjustments.py는 정확히 같은 이름만 할증).
- 조건 값: when / blocked_if / blocked_if_all 이 없는 입력을 쓰거나, 선택지 밖 값과 비교하면 영원히 안 맞는다.
- 비용 분류: cost_rules[].category 는 재료비·노무비·경비 중 하나(원가계산서가 이 세 칸만 더한다).
- 표 참조: quantity_model 이 가리키는 표 id 가 카드의 tables 에 있는지.
- 대표값 표(data/defaults/input_assumptions.json): 카드의 모든 입력에 항목이 있고, 대표값·키워드가 선택지 안에 있는지.

예전부터 있던 결함은 evals/spec_lint_known.json 에 적어 두고 새 결함만 실패로 본다. 고치면 목록에서 지운다.
사용: python -B evals/check_spec_lint.py [--update-known]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from check_spec_source_match import broken_text

ROOT = Path(__file__).resolve().parents[1]
KNOWN = ROOT / "evals/spec_lint_known.json"
CATEGORIES = {"재료비", "노무비", "경비"}
ASSUMPTIONS = ROOT / "data/defaults/input_assumptions.json"
KINDS = {"work", "site", "special", "quantity"}


def walk(node, key=None):
    """(부모 키, 값)을 깊이 우선으로 낸다."""
    yield key, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, key)


def cards():
    """운영 로더(specs.py)와 같은 범위: 검토 명세 전부 + 실행 목록에 있는 초안."""
    executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
    for path in sorted((ROOT / "backend/agent/rules/specs").rglob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package.get("draft", {}).get("id") in executable:
            yield path, package


def line_names(spec: dict) -> set[str]:
    """계산 결과 줄 이름이 될 수 있는 직종·장비 이름.

    표의 행·열 이름도 줄 이름이 될 수 있다(장비 행 등). 다만 입력 선택지로 고르는 행·열(작업 종류, 관경 등)은
    줄 이름이 아니므로 뺀다 — 9-5-9처럼 작업 이름을 할증 대상으로 적은 경우를 잡기 위해서다.
    """
    names = set()
    for key, value in walk(spec.get("quantity_model") or {}):
        if key in ("trades", "trade") and isinstance(value, str):
            names.add(value)
        elif isinstance(value, dict) and "equipment" in str(key) and isinstance(value.get("name"), str):
            names.add(value["name"])
    choices = {value for field in spec.get("inputs", []) if isinstance(field.get("allowed_values"), list)
               for value in field["allowed_values"] if isinstance(value, str)}
    for table in spec.get("tables", []):
        for _, value in walk(table.get("values") or {}):
            if isinstance(value, dict):
                names |= {key for key in value if key not in choices}
    return names


def conditions(spec: dict):
    """(입력 이름, 비교 값) — when 사전과 blocked_if(_all)의 == 비교."""
    for key, value in walk(spec):
        if key == "when" and isinstance(value, dict) and "input" in value:  # {"input": 이름, "equals": 값} 형태
            if "equals" in value:
                yield value["input"], value["equals"]
        elif key == "when" and isinstance(value, dict):
            yield from ((name, expected) for name, expected in value.items() if not isinstance(expected, dict))
        elif key in ("blocked_if", "blocked_if_all"):
            for rule in value if isinstance(value, list) else [value]:
                if isinstance(rule, dict) and rule.get("op") in ("==", "!=") and "input" in rule:
                    yield rule["input"], rule.get("value")


def check(package: dict) -> list[str]:
    spec = package.get("draft") or package
    model = spec.get("quantity_model") or {}
    found = []
    if broken_text(package):
        found.append("깨진 글자")
    names = line_names(spec)
    squashed = {re.sub(r"\s+", "", name): name for name in names}
    for key, value in walk(model):
        if key == "applies_to" and isinstance(value, str) and value not in names:
            near = squashed.get(re.sub(r"\s+", "", value))
            found.append(f"할증 대상 '{value}'" + (f" ≠ 직종 '{near}'(띄어쓰기)" if near else " 은 카드의 직종·장비가 아님"))
    inputs = {field["name"]: field for field in spec.get("inputs", [])}
    for name, expected in conditions(spec):
        field = inputs.get(name)
        if field is None:
            found.append(f"조건이 없는 입력 '{name}' 을 씀")
            continue
        allowed = field.get("allowed_values")
        if isinstance(expected, str):
            expected = re.sub(r"^\s*(?:==|!=)\s*", "", expected)  # '!=탄소강관' 처럼 연산자를 붙인 값
        if field.get("type") == "enum" and isinstance(allowed, list) and isinstance(expected, str) \
                and not re.fullmatch(r"\s*(>=|<=|>|<)\s*\d+(?:\.\d+)?\s*", expected) and expected not in allowed:
            found.append(f"조건 '{name}' = '{expected}' 는 선택지에 없음")
        if field.get("type") == "boolean" and not isinstance(expected, bool):
            found.append(f"조건 '{name}' 은 참/거짓인데 '{expected}' 와 비교")
    for rule in spec.get("cost_rules", []):
        # price.py 는 base·category·name·rate·cite 를 바로 꺼내 쓴다. 하나라도 다르면 가격 계산이 오류로 멈춘다.
        missing = [key for key in ("base", "category", "name", "rate", "cite") if key not in rule]
        if missing:
            found.append(f"비용 규칙에 {'·'.join(missing)} 없음(가격 계산 오류)")
        elif rule["base"] != "labor_subtotal":
            found.append(f"비용 규칙 기준 '{rule['base']}' 는 계산기가 지원하지 않음(가격 계산 오류)")
        if "category" in rule and rule["category"] not in CATEGORIES:
            found.append(f"비용 분류 '{rule['category']}' 는 재료비·노무비·경비가 아님(가격 계산 오류)")
    table_ids = {table.get("id") for table in spec.get("tables", [])}
    table_ids |= {(table.get("cite") or {}).get("table_id") for table in spec.get("tables", [])}
    for key, value in walk(model):
        if key == "table" and isinstance(value, str) and value not in table_ids:
            found.append(f"없는 표 '{value}' 를 참조")
    return sorted(set(found))


def module_inputs() -> dict[tuple[str, str], list[dict]]:
    """specs.py 처럼 승인된 계산 모듈이 절에 더하는 입력."""
    extra: dict[tuple[str, str], list[dict]] = {}
    for path in sorted((ROOT / "data/calculation_modules/approved").glob("*.json")):
        module = json.loads(path.read_text(encoding="utf-8"))
        if module.get("review_status") == "approved_for_runtime":
            for section in module.get("sections", []):
                extra.setdefault((section["division"], section["section_no"]), []).extend(module.get("inputs", []))
    return extra


def check_assumptions(spec: dict, entry: dict | None) -> list[str]:
    """대표값 표 한 카드분. 계산기가 이름·값을 글자 그대로 비교하므로 선택지 밖 대표값은 조용히 안 맞는다."""
    if entry is None:
        return ["대표값 표에 카드 없음"]
    found = ["대표값 표 깨진 글자"] if broken_text(entry) else []
    inputs = {field["name"]: field for field in spec.get("inputs", [])}
    found += [f"입력 '{name}' 대표값 없음" for name in inputs.keys() - entry.keys()]
    found += [f"대표값 표에 없는 입력 '{name}'" for name in entry.keys() - inputs.keys()]
    for name, info in entry.items():
        field = inputs.get(name)
        if not field:
            continue
        allowed = field.get("allowed_values") if isinstance(field.get("allowed_values"), list) else None
        default = info.get("default")
        if info.get("kind") not in KINDS:
            found.append(f"입력 '{name}' 종류 '{info.get('kind')}'")
        if default is not None and allowed is not None and default not in allowed:
            found.append(f"입력 '{name}' 대표값 '{default}' 는 선택지에 없음")
        choices = {str(value).lower() if isinstance(value, bool) else value for value in allowed or []}
        for value in info.get("keywords") or {}:
            if allowed is not None and value not in choices:
                found.append(f"입력 '{name}' 키워드 대상 '{value}' 는 선택지에 없음")
    return found


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    results = {}
    assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))["cards"] if ASSUMPTIONS.is_file() else None
    extra = module_inputs()
    reviewed = set()  # 운영 로더는 같은 id의 검토 명세를 초안보다 우선한다 → 대표값은 검토 명세 기준으로만 본다
    for path, package in cards():
        problems = check(package)
        spec = package.get("draft") or package
        is_draft = "draft" in package
        if not is_draft:
            reviewed.add(spec.get("id"))
        if assumptions is not None and not (is_draft and spec.get("id") in reviewed):
            known = {field["name"] for field in spec.get("inputs", [])}
            added = [f for f in extra.get((spec.get("division"), spec.get("section_no")), []) if f.get("name") not in known]
            merged = {**spec, "inputs": spec.get("inputs", []) + added}
            problems = sorted(set(problems) | set(check_assumptions(merged, assumptions.get(spec.get("id")))))
        if problems:
            results[path.relative_to(ROOT).as_posix()] = problems
    if "--update-known" in argv:
        KNOWN.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"기존 결함 목록 저장: {sum(map(len, results.values()))}건")
        return 0
    known = json.loads(KNOWN.read_text(encoding="utf-8")) if KNOWN.is_file() else {}
    new = {path: [p for p in problems if p not in known.get(path, [])] for path, problems in results.items()}
    new = {path: problems for path, problems in new.items() if problems}
    fixed = sum(1 for path, problems in known.items() for p in problems if p not in results.get(path, []))
    for path, problems in new.items():
        for problem in problems:
            print(f"새 결함  {path}: {problem}")
    print(f"카드 검사: 기존 결함 {sum(map(len, results.values())) - sum(map(len, new.values()))}건, "
          f"새 결함 {sum(map(len, new.values()))}건, 고쳐진 기존 결함 {fixed}건")
    if fixed:
        print("고쳐진 결함은 --update-known 으로 목록에서 지우세요.")
    return 1 if new else 0


def _selftest():
    card = {"inputs": [{"name": "road", "type": "enum", "allowed_values": ["시가지 도로"]}],
            "tables": [{"id": "t1"}],
            "quantity_model": {"params": {"unit_rate_table": {"table": "t1", "trades": ["특별 인부"]},
                                          "surcharges": [{"when": {"road": "시가지"}, "applies_to": ["특별인부", "객체추출"]}]}},
            "cost_rules": [{"category": "material cost", "base": "labor_subtotal", "name": "x", "rate": "0.02", "cite": {}},
                           {"item": "tooling", "rate": "0.02", "basis": "labor"}]}
    found = check(card)
    assert any("띄어쓰기" in f for f in found) and any("'객체추출' 은" in f for f in found), found
    assert any("선택지에 없음" in f for f in found) and any("비용 분류" in f for f in found), found
    assert any("base·category·name·cite 없음" in f for f in found), found
    card["quantity_model"]["params"]["surcharges"][0] = {"when": {"input": "road", "equals": "시가지 도로"},
                                                         "applies_to": ["특별 인부"]}
    card["cost_rules"] = [{"category": "경비", "base": "labor_subtotal", "name": "x", "rate": "0.02", "cite": {}}]
    assert check(card) == [], check(card)
    bad = check_assumptions(card, {"road": {"kind": "site", "default": "시가지", "keywords": {"교외": ["x"]}}})
    assert len(bad) == 2 and all("선택지에 없음" in f for f in bad), bad
    assert check_assumptions(card, {}) == ["입력 'road' 대표값 없음"]
    assert check_assumptions(card, {"road": {"kind": "site", "default": "시가지 도로"}}) == []


if __name__ == "__main__":
    _selftest()
    raise SystemExit(main(sys.argv[1:]))

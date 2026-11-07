"""대표값 표(data/defaults/input_assumptions.json)의 ratio·ask를 실제 계산기로 다시 채운다. 외부 호출 없음.

조건 하나만 허용값마다 바꿔 직접공사비(priced.total_exact, 단가가 없으면 1단위당 품의 합)를 구하고, 최댓값/최솟값을 ratio로 적는다.
나머지 조건은 대표값(없으면 첫 허용값, 수치는 1)으로 둔다.

ask(사용자가 말하지 않았을 때 먼저 물어볼지):
- 물량(kind=quantity)·대표값 없음 → 묻는다
- ratio ≥ ASK_RATIO(금액이 2배 이상 바뀜) → 묻는다
- 계산이 막혀 ratio를 못 잰 작업 정의(kind=work) → 묻는다
- 나머지 → 대표값으로 가정하고 화면에 '가정'으로 표시

사용(저장소 루트): python -B pipeline/measure_input_impact.py
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.estimate import tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402

PATH = ROOT / "data/defaults/input_assumptions.json"
ASK_RATIO = Decimal(2)


def amounts(spec: dict, values: dict) -> tuple[Decimal | None, Decimal | None]:
    """(직접공사비, 1단위당 품의 합). 못 내면 None. 둘은 단위가 달라 서로 비교하지 않는다."""
    session = tools.new_estimate("대표값 영향 측정", "2026-10-01")
    tools.choose_work(tools._item(session), {"confirmed": True, "section": spec["title"]}, spec)
    tools.set_conditions(session, "", values={k: {"value": v} for k, v in values.items()}, source="answer")
    cost = labor = None
    try:
        result = tools.estimate_cost(session)
        if result["status"] == "ok":
            total = Decimal(str((result["data"].get("priced") or {}).get("total_exact") or 0))
            cost = total if total > 0 else None
        result = tools.compute_labor(session, allow_per_unit=True)
    except Exception:  # noqa: BLE001 - 계산 실패는 '측정 불가'로 둔다
        return cost, None
    if result["status"] == "ok":
        total = Fraction(0)
        try:
            for line in result["data"].get("unit_lines") or []:
                total += Fraction(line.get("exact") or 0)
        except ValueError:  # '1.70∼2.00' 같은 범위 값은 한 수가 아니라 측정에서 뺀다
            total = Fraction(0)
        labor = Decimal(total.numerator) / Decimal(total.denominator) if total > 0 else None
    return cost, labor


def applies(field: dict, values: dict) -> bool:
    when = field.get("when")
    return not when or values.get(when["input"]) == when["equals"]


def base_values(spec: dict, entry: dict) -> dict:
    values = {}
    for field in spec["inputs"]:
        default = (entry.get(field["name"]) or {}).get("default")
        allowed = field.get("allowed_values")
        values[field["name"]] = default if default is not None else (
            allowed[0] if isinstance(allowed, list) and allowed else "1")
    fields = {field["name"]: field for field in spec["inputs"]}
    return {name: value for name, value in values.items() if applies(fields[name], values)}


def ratio_of(spec: dict, field: dict, base: dict) -> Decimal | None:
    allowed = field.get("allowed_values")
    if not isinstance(allowed, list) or len(allowed) < 2 or not applies(field, base):
        return None
    measured = [amounts(spec, {**base, field["name"]: value}) for value in allowed]
    # 금액을 둘 이상 낼 수 있으면 금액으로, 아니면 품으로. 한 비교 안에서 단위를 섞지 않는다.
    for index in (0, 1):
        totals = [pair[index] for pair in measured if pair[index]]
        if len(totals) >= 2:
            return max(totals) / min(totals)
    return None


def should_ask(info: dict, ratio: Decimal | None, single: bool = False) -> bool:
    if info["kind"] == "quantity" or info.get("default") is None:
        return True
    if single:  # 선택지가 하나뿐이면 물을 필요가 없다
        return False
    if ratio is not None:
        return ratio >= ASK_RATIO
    return info["kind"] == "work"


def _selftest() -> None:
    site, work = {"kind": "site", "default": "a"}, {"kind": "work", "default": "a"}
    assert should_ask({"kind": "quantity", "default": None}, None)
    assert should_ask({"kind": "site", "default": None}, Decimal("1.1"))
    assert should_ask(site, Decimal("2")) and not should_ask(site, Decimal("1.99"))
    assert should_ask(work, None) and not should_ask(site, None) and not should_ask(work, None, single=True)


def main() -> int:
    _selftest()
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads(PATH.read_text(encoding="utf-8"))
    specs = load_specs()
    for spec_id, entry in data["cards"].items():
        spec = specs.get(spec_id)
        if not spec:
            continue
        base = base_values(spec, entry)
        for field in spec["inputs"]:
            info = entry.get(field["name"])
            if not info:
                continue
            ratio = ratio_of(spec, field, base)
            info["ratio"] = f"{ratio:.2f}" if ratio is not None else None
            allowed = field.get("allowed_values")
            info["ask"] = should_ask(info, ratio, isinstance(allowed, list) and len(allowed) == 1)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    infos = [info for entry in data["cards"].values() for info in entry.values()]
    print(f"카드 {len(data['cards'])}, 조건 {len(infos)}, 먼저 묻기 {sum(i['ask'] for i in infos)}, "
          f"그중 물량 {sum(i['ask'] and i['kind'] == 'quantity' for i in infos)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

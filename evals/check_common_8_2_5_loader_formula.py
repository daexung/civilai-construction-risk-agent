"""공통 8-2-5 로더 시간당 작업량: 원문 표 숫자를 손으로 옮긴 기대값과 대조(명세·계산기 출력 재사용 안 함)."""
from __future__ import annotations

import itertools
import json
import sys
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity  # noqa: E402

spec = json.loads((ROOT / "data/drafts/specs/공통/8-2-5.json").read_text(encoding="utf-8"))["draft"]
K_TEXT = {f["name"]: f for f in spec["inputs"]}["k_condition"]["allowed_values"]
K_VAL = dict(zip(K_TEXT, ["1.2", "1.0", "0.9", "0.7", "0.55"]))
T1 = {"용이한경우": (5, 20, 6, 22), "보통인경우": (8, 29, 9, 32), "약간곤란한 경우": (9, 36, 14, 41), "곤란한경우": (11, None, 18, None)}
E = {("모래, 사질토", "자연상태"): ("0.70", "0.55", "0.40"), ("모래, 사질토", "흐트러진 상태"): ("0.75", "0.60", "0.45"),
     ("자갈 섞인 흙, 점성토", "자연상태"): ("0.60", "0.45", "0.30"), ("자갈 섞인 흙, 점성토", "흐트러진 상태"): ("0.60", "0.50", "0.35"),
     ("파쇄암", "흐트러진 상태"): ("0.55", "0.35", "0.25")}
COND = ["양호", "보통", "불량"]
checked = skipped = 0
for lt, t1c, method, kc, (soil, state), cond, trench in itertools.product(
        ("무한궤도식", "타이어식"), T1, ("산적상태에서 담을 때", "지면부터 굴착 집토하여 담을 때"),
        K_TEXT, E, COND, (False, True)):
    spec_label = "0.95㎥" if lt == "타이어식" else "0.57㎥"  # 규격=버킷용량 q, 흐트러진 상태 기준이라 f=1
    inputs = {"machine_spec": spec_label, "volume_basis": "흐트러진 상태", "quantity": "1", "fuel_price": "1", "loader_type": lt, "l": "8", "t1_condition": t1c, "t1_method": method,
              "k_condition": kc, "e_soil_type": soil, "e_state": state, "e_condition": cond, "is_trench": trench}
    r = formula_quantity(spec, inputs)
    tire = lt == "타이어식"
    if tire and kc == K_TEXT[4]:
        assert r["status"] == "blocked", r; skipped += 1; continue
    t1 = T1[t1c][(2 if tire else 0) + (0 if method.startswith("산적") else 1)]
    if t1 is None:
        assert r["status"] == "rejected", (t1c, method, r); skipped += 1; continue
    e_cond = "양호" if (tire and state == "흐트러진 상태" and soil != "파쇄암") else cond
    e = F(E[(soil, state)][COND.index(e_cond)]) - (F(1, 20) if trench else 0)
    cm = (F(2) if lt == "무한궤도식" else F("1.8")) * 8 + t1 + 14
    q = 3600 * F(spec_label[:-1]) * F(K_VAL[kc]) * e / cm
    assert r["status"] == "computed", r
    got = {l["name"]: l["exact"] for l in r["unit_lines"]}
    assert got is not None, list(r)
    assert F(got["시간당 작업량 Q"]) == q and F(got["1회 싸이클 시간 cm"]) == cm and F(got["로더"]) == 1 / q, (inputs, got, q)
    checked += 1
# 원문에 값이 없는 칸(파쇄암 자연상태)은 거부해야 한다
r = formula_quantity(spec, {"machine_spec": "0.57㎥", "volume_basis": "흐트러진 상태", "quantity": "1", "fuel_price": "1", "loader_type": "무한궤도식", "l": "8", "t1_condition": "보통인경우",
     "t1_method": "산적상태에서 담을 때", "k_condition": K_TEXT[0], "e_soil_type": "파쇄암", "e_state": "자연상태",
     "e_condition": "보통", "is_trench": False})
assert r["status"] == "rejected", r
print(json.dumps({"checked_routes": checked, "fail_closed_routes": skipped}))

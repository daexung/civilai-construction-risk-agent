"""공통 8-2-3 굴착기 시간당 작업량: 원문 표 숫자를 손으로 옮긴 기대값과 대조."""
from __future__ import annotations

import itertools
import json
import sys
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity  # noqa: E402

spec = json.loads((ROOT / "data/drafts/specs/공통/8-2-3.json").read_text(encoding="utf-8"))["draft"]
fields = {f["name"]: f for f in spec["inputs"]}
K_TEXT = fields["bucket_condition"]["allowed_values"]
K = dict(zip(K_TEXT, ["1.10", "0.90", "0.70", "0.55"]))
SOIL = fields["soil_type"]["allowed_values"]  # 모래,사질토 / 자갈섞인흙,점성토 / 파쇄암
E = {(SOIL[0], "자연상태"): ("0.85", "0.70", "0.55"), (SOIL[0], "흐트러진 상태"): ("0.90", "0.75", "0.60"),
     (SOIL[1], "자연상태"): ("0.75", "0.60", "0.45"), (SOIL[1], "흐트러진 상태"): ("0.80", "0.65", "0.50"),
     (SOIL[2], "흐트러진 상태"): (None, "0.45", "0.35")}
RES = {(SOIL[0], "보통"): "0.30", (SOIL[0], "불량"): "0.19", (SOIL[1], "보통"): "0.26", (SOIL[1], "불량"): "0.15"}
CM = {"0.12∼0.4": (13, 15, 18, 20), "0.6∼0.8": (16, 18, 20, 22), "1.0∼1.2": (17, 19, 21, 23), "2.0": (22, 25, 27, 30)}
MACHINES = {"0.12㎥": "0.12∼0.4", "0.40㎥": "0.12∼0.4", "0.60㎥": "0.6∼0.8", "0.80㎥": "0.6∼0.8", "1.00㎥": "1.0∼1.2", "2.00㎥": "2.0"}
COND = ["양호", "보통", "불량"]
ANG = ["45", "90", "135", "180"]
ok = closed = 0
for kc, soil, state, cond, trench, uw, res, cap_label, ang in itertools.product(
        K_TEXT, SOIL, ("자연상태", "흐트러진 상태"), COND, (False, True), (False, True), (False, True), MACHINES, ANG):
    cap = MACHINES[cap_label]
    inputs = {"machine_spec": cap_label, "volume_basis": "흐트러진 상태", "quantity": "1", "fuel_price": "1", "bucket_condition": kc, "soil_type": soil,
              "soil_state": state, "site_condition": cond, "is_trenching": trench, "is_underwater": uw,
              "is_residential_area": res, "swing_angle": ang}
    r = formula_quantity(spec, inputs)
    eff_cond = "불량" if uw else cond
    if res and trench:
        assert r["status"] == "blocked", r; closed += 1; continue
    base = RES.get((soil, eff_cond)) if res and state == "자연상태" else (
        None if res else E.get((soil, state), (None,) * 3)[COND.index(eff_cond)])
    if base is None:
        assert r["status"] == "rejected", (inputs, r); closed += 1; continue
    e = F(base) - (F(1, 20) if trench else 0)
    q = 3600 * F(cap_label[:-1]) * F(K[kc]) * e / CM[cap][ANG.index(ang)]
    assert r["status"] == "computed", (inputs, r)
    assert F(r["unit_lines"][0]["exact"]) == q and F(r["unit_lines"][1]["exact"]) == 1 / q, (inputs, r["unit_lines"], q)
    ok += 1
print(json.dumps({"computed_routes": ok, "fail_closed_routes": closed}))

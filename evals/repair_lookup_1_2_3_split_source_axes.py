"""Expose the independent 1-2-3 source tables through exact source routes."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/1-2-3.json"
BACKUP = ROOT / "tmp/1-2-3-before-independent-source-routes.json"


def main() -> int:
    if not BACKUP.exists():
        shutil.copy2(SPEC, BACKUP)
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["inputs"] = [{
        "name": "lookup_view",
        "type": "enum",
        "allowed_values": ["토질별 체적 변화율", "상태 간 체적환산계수"],
        "unit": None,
        "required": True,
        "ask": "어느 원문 자료를 조회할까요?",
        "source": "p64-t0/p65-t0 체적 변화율, p65-t1 체적환산계수(f) 표",
        "source_table_map": {
            "토질별 체적 변화율": ["p64-t0", "p65-t0"],
            "상태 간 체적환산계수": "p65-t1",
        },
    }]
    draft["quantity_model"]["steps"] = [
        "선택한 원문 표를 원문 행·열 값과 인용을 붙여 조회한다.",
        "토질별 L·C 범위는 원문 범위 그대로 제시하며, 범위 안의 값을 임의로 선택하지 않는다.",
        "상태 간 환산계수는 표에 적힌 기호식 그대로 제시하며, L·C의 수치 대입은 수행하지 않는다.",
    ]
    draft["quantity_model"]["source"] = "3. 체적환산계수 나~라, PDF 64~65쪽"
    draft["work"] = "체적 변화율 및 상태 간 체적환산계수 원문표 조회"
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"spec": str(SPEC), "backup": str(BACKUP),
                      "routes": draft["inputs"][0]["source_table_map"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

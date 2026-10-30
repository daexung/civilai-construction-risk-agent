"""Route the three source tables and their independent axes without false joint inputs."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/2-2-3.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    if not (ROOT / "tmp/2-2-3-spec-before-independent-rate-routes.json").exists():
        (ROOT / "tmp/2-2-3-spec-before-independent-rate-routes.json").write_bytes(SPEC.read_bytes())
    spec = package["draft"]
    category = next(field for field in spec["inputs"] if field["name"] == "facility_category")
    category["source_table_map"] = {
        "철제조립식 가설건축물": "p94-t1",
        "콘테이너형 가설건축물": "p95-t1",
        "가설울타리 및 가설방음벽": "p95-t2",
    }
    spec["inputs"] = [field for field in spec["inputs"] if field["name"] != "building_type"]
    rate_basis = {
        "name": "rate_basis", "type": "enum",
        "allowed_values": ["손율(%)", "부자재율 (%) 사무실", "부자재율 (%) 창고"],
        "unit": None, "required": True,
        "ask": "철제조립식 가설건축물에서 어느 비율을 조회합니까? (손율 또는 사무실/창고 부자재율)",
        "source": "PDF 38쪽 1. 철제조립식 가설건축물 표의 행 구분",
        "source_row_key": True,
        "synonyms": {"손율(%)": ["손율"], "부자재율 (%) 사무실": ["부자재율 사무실", "사무실 부자재율"],
                     "부자재율 (%) 창고": ["부자재율 창고", "창고 부자재율"]},
        "when": {"input": "facility_category", "equals": "철제조립식 가설건축물"},
    }
    next(field for field in spec["inputs"] if field["name"] == "duration_prefab")["when"] = {
        "input": "facility_category", "equals": "철제조립식 가설건축물"}
    next(field for field in spec["inputs"] if field["name"] == "duration_container")["when"] = {
        "input": "facility_category", "equals": "콘테이너형 가설건축물"}
    next(field for field in spec["inputs"] if field["name"] == "fence_material")["when"] = {
        "input": "facility_category", "equals": "가설울타리 및 가설방음벽"}
    next(field for field in spec["inputs"] if field["name"] == "duration_fence")["when"] = {
        "input": "facility_category", "equals": "가설울타리 및 가설방음벽"}
    fence_material = next(field for field in spec["inputs"] if field["name"] == "fence_material")
    material_headers = {
        "전기아연도금강판": "손 율 (%) 전기아연도금강판",
        "재생플라스틱방음판": "손 율 (%) 재생플라스틱방음판",
        "스틸방음판": "손 율 (%) 스틸방음판",
    }
    fence_material["allowed_values"] = list(material_headers.values())
    fence_material["synonyms"] = {header: [material] for material, header in material_headers.items()}
    insert_at = next(i for i, field in enumerate(spec["inputs"]) if field["name"] == "duration_prefab")
    spec["inputs"].insert(insert_at, rate_basis)
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("three exact table routes and mutually exclusive rate/duration/material axes installed")


if __name__ == "__main__":
    main()

"""Expanded service routing, quantity extraction, defaults, and A1 API regression."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from backend.agent.nodes.fill import extract_inputs, fill  # noqa: E402
from backend.agent.nodes.route import route  # noqa: E402
from backend.agent.nodes.retrieve import get_search  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.state import new_state  # noqa: E402
from backend.api.main import app  # noqa: E402
from backend.api.tables import estimate_filename  # noqa: E402
from backend.agent.tools.search.vector import MissingVectorsError, VectorIndex  # noqa: E402


NEGATIVE = [
    "오늘 날씨 어때", "파이썬으로 정렬 코드 짜줘", "점심 메뉴 추천", "영화 줄거리 알려줘",
    "서울 여행 계획 짜줘", "영어 문장 번역해줘", "내일 일정 알려줘", "사진 색감 바꿔줘",
    "축구 경기 결과 알려줘", "요리법 추천해줘",
]
POSITIVE = [
    "수성페인트 100㎡ 붓칠 비용", "자동문 3개소 설치 인건비", "철골 100톤 세우기 품량",
    "배관 20m 설치", "창호 3개 설치", "펌프 2대 시공", "콘크리트 100㎥ 타설",
    "바닥 50㎡ 시공", "교량 철근 2t 가공", "가설재 해체 공수",
]
UNITS = [
    ("자동문 3개소 설치", "개소", "3"), ("바닥 100㎡", "㎡", "100"),
    ("바닥 100m2", "㎡", "100"), ("바닥 100 제곱미터", "㎡", "100"),
    ("철골 100ton", "ton", "100"), ("철골 100톤", "ton", "100"),
    ("철골 100t", "ton", "100"), ("배관 20m", "m", "20"),
]


def _draft(division: str) -> dict:
    return next(spec for spec in load_specs().values()
                if spec.get("origin") == "draft" and spec["division"] == division)


def main() -> int:
    checks = []
    checks += [(f"route negative {i}", route(new_state(query))["status"] == "OUT_OF_SCOPE")
               for i, query in enumerate(NEGATIVE, 1)]
    checks += [(f"route positive {i}", route(new_state(query))["route"] == "estimate")
               for i, query in enumerate(POSITIVE, 1)]
    for i, (query, unit, expected) in enumerate(UNITS, 1):
        spec = {"inputs": [{"name": "quantity", "type": "positive_rational", "unit": unit}],
                "quantity_model": {"params": {"quantity_input": "quantity"}}}
        values, _ = extract_inputs(query, spec)
        checks.append((f"quantity unit {i}", values.get("quantity") == expected))
    for division, expected in (("건축", "주택 외 건축"), ("공통", "기타 토목공사"),
                               ("유지관리", "기타 토목공사")):
        spec = _draft(division)
        state = {"query": "품셈 비용", "spec_id": spec["id"], "inputs": {}, "input_sources": {},
                 "selection": {"confirmed": True}, "reply": ""}
        result = fill(state)
        checks.append((f"default {division}", result["inputs"]["work_category"] == expected
                       and result["input_sources"]["work_category"] == "기본값(부문)"))

    # TestClient without lifespan tests the request flow; startup completeness is tested separately.
    os.environ["AGENT_OFFLINE"] = "1"
    os.environ["AGENT_LLM"] = "off"
    os.environ.pop("INDEX_CONFIG", None)
    get_search.cache_clear()
    response = TestClient(app).post("/api/chat", json={
        "message": "자동문 3개소 설치 비용 알려줘", "basis_date": "2026-10-01"}).json()
    print("A1", json.dumps({key: response.get(key) for key in ("status", "work", "questions")}, ensure_ascii=False))
    print("A1 price", response.get("priced", {}).get("total") if response.get("priced") else None,
          "statement", response.get("statement", {}).get("totals") if response.get("statement") else None)
    checks.append(("A1 route and work", response["status"] in ("PARTIAL", "OK")
                   and response["work"]["title"] == "건축 10-1-7 자동문 설치"))
    checks.append(("A1 building default", any(item["name"] == "work_category"
                   and item["value"] == "주택 외 건축" and item["source"] == "기본값(부문)"
                   for item in response["inputs"])))
    statement = response.get("statement") or {}
    checks.append(("A1 contract", statement.get("totals", {}).get("contract_amount") == 2727421))
    priced = response.get("priced") or {}
    lines = {line["name"]: line for line in priced.get("lines", [])}
    checks.append(("A1 unit prices", priced.get("total") == "483906"
                   and [lines[name]["amount"] for name in ("창호공", "기계설비공", "보통인부")]
                   == ["211264.9", "181985.2", "81168.0"]))
    checks.append(("A1 direct and tool cost", (priced.get("reference_amounts") or {}).get("total") == "1451718"
                   and any(line["amount"] == "9488.3" for line in priced.get("cost_lines", []))))
    checks.append(("A1 review and filename", response.get("result", {}).get("review_status") == "AI 초안 · 검토 전"
                   and estimate_filename(response) == "자동문 설치_견적서.xlsx"))

    import pyarrow.parquet as pq
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
    vector_table = pq.read_table(ROOT / "data/processed/embeddings.parquet")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)
        (path / "chunks.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in chunks[:2]), encoding="utf-8")
        one_vector = vector_table.filter(__import__("pyarrow.compute", fromlist=["equal"]).equal(
            vector_table["chunk_id"], chunks[0]["chunk_id"]))
        pq.write_table(one_vector, path / "vectors.parquet")
        config = path / "index.json"
        config.write_text(json.dumps({"chunks": str(path / "chunks.jsonl"),
                                      "vectors": str(path / "vectors.parquet"),
                                      "embed_provider": "studio", "divisions": ["공통"]}), encoding="utf-8")
        try:
            VectorIndex(config_path=config)
        except MissingVectorsError as exc:
            checks.append(("missing vector division count", "공통 1개" in str(exc)))
        else:
            checks.append(("missing vector division count", False))
    with patch("backend.api.main.get_search", side_effect=MissingVectorsError("공통 1개")):
        with TestClient(app) as client:
            health = client.get("/api/health").json()
            deadline = time.monotonic() + 2
            while health.get("status") == "warming" and time.monotonic() < deadline:
                time.sleep(0.01)
                health = client.get("/api/health").json()
            unavailable = client.post("/api/chat", json={"message": "estimate"}).status_code
    checks.append(("missing vectors keep service unready", health == {"status": "error"} and unavailable == 503))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

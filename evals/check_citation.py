"""품셈 인쇄 쪽, 원문 인용, 표 이미지 및 채팅 전달을 오프라인 검사한다."""

from __future__ import annotations

import json
import os
import re
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.agent.tools.source.citation import CHUNKS, PDF, cite_note, cite_table, resolve_cites  # noqa: E402
import backend.api.main as api_main  # noqa: E402
from backend.api.main import app  # noqa: E402
from pipeline.page_map import KNOWN, summarize  # noqa: E402


def main() -> int:
    checks: list[tuple[str, bool]] = []
    page_map = json.loads((ROOT / "data/processed/page_map.json").read_text(encoding="utf-8"))
    checks.append(("C1 알려진 PDF/인쇄 쪽 5개", all(
        page_map["pages"][str(pdf)]["printed_page"] == printed for pdf, printed in KNOWN.items())))
    checks.append(("C2 모든 쪽 매핑 또는 사유", len(page_map["pages"]) == 982 and all(
        entry["printed_page"] is not None or entry["number_reason"]
        for entry in page_map["pages"].values())))

    table = cite_table("p187-t0", "15㎝", "철근", "130")
    checks.append(("C3 시공량 표 인용", table["division"] == "공통부문"
                   and table["section_no"] == "6-1-4"
                   and table["subsection"] == "3. 일일시공량"
                   and table["printed_page"] == page_map["pages"]["187"]["printed_page"]
                   and "6-1-4 콘크리트 펌프차 타설" in table["label"]
                   and "3. 일일시공량" in table["label"]
                   and "보완" not in table["label"]
                   and "표: 슬럼프 15㎝ · 철근구조물 → 130㎥/일" in table["label"]
                   and table["internal_id"] == "p187-t0"))

    note1 = cite_note("6-1-4", "2", "①")
    note2 = cite_note("6-1-4", "2", "②")
    reset = cite_note("6-1-4", "3", "※")
    checks.append(("C4 진동기 주석", "진동기를 사용하지 않는 경우" in (note1["quote"] or "")))
    checks.append(("C5 경장비 주석", "5%" in (note2["quote"] or "")))
    checks.append(("C6 재셋팅 주석", "회당 \n시공량의 5%" in (reset["quote"] or "")))
    with __import__("pymupdf").open(PDF) as document:
        exact_quotes = all(note["quote"] in document[note["pdf_page"] - 1].get_text("text")
                           for note in (note1, note2, reset))
    checks.append(("C7 인용문 PDF 원문 그대로", exact_quotes))

    spec = json.loads((ROOT / "backend/agent/rules/specs/common/6-1-4_pump.json").read_text(encoding="utf-8"))
    unresolved = []
    for group in ("tables", "crew_rules", "blocked", "not_calculated"):
        for index, item in enumerate(spec[group]):
            try:
                citations = resolve_cites(item.get("cite"))
                if not citations or any(c["division"] is None or c["printed_page"] is None
                                        or (c["item"] != "표" and c["quote"] is None) for c in citations):
                    unresolved.append(f"{group}[{index}]")
            except (LookupError, FileNotFoundError, KeyError) as error:
                unresolved.append(f"{group}[{index}]: {error}")
    checks.append(("C8 명세 cite 전부 인용 가능", not unresolved))
    if unresolved:
        print("풀지 못한 항목:", ", ".join(unresolved))

    client = TestClient(app)
    start = client.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"}).json()
    computed = client.post("/api/chat", json={"thread_id": start["thread_id"], "answers": {
        "pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
        "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
        "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
        "project_scale": "이 견적만",
    }}).json()
    result = computed.get("result") or {}
    lines = result.get("unit_lines", [])
    checks.append(("C9 계산 응답의 각 수량 인용", computed["status"] == "PARTIAL"
                   and len(lines) == 5 and all(line.get("citations") for line in lines)
                   and all(not re.search(r"p\d+-t\d+", citation["label"])
                           for line in lines for citation in line["citations"])
                   and all(line.get("citations") for line in result.get("lines", []))
                   and bool(result.get("daily_volume", {}).get("citations"))))
    image = client.get("/api/source/p187-t0.png")
    missing = client.get("/api/source/p999-t0.png")
    checks.append(("C10 표 PNG와 없는 표 404", image.status_code == 200
                   and image.headers.get("content-type") == "image/png"
                   and image.content.startswith(b"\x89PNG\r\n\x1a\n")
                   and missing.status_code == 404
                   and any(c.get("image_url") == "/api/source/p187-t0.png"
                           for c in result.get("daily_volume", {}).get("citations", []))))

    blocked_start = client.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"}).json()
    blocked = client.post("/api/chat", json={"thread_id": blocked_start["thread_id"], "answers": {
        "pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
        "placement": "붐", "vibrator_used": True, "reset_status": "있음", "concrete_supply": "관급",
        "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
        "project_scale": "이 견적만",
    }}).json()
    checks.append(("C11 보류 사유 원문 주석", blocked["status"] == "BLOCKED"
                   and any("회당 \n시공량의 5%" in (c["quote"] or "")
                           for c in blocked["result"].get("citations", []))))

    if CHUNKS.name == "chunks.all.jsonl":
        outside = resolve_cites({"chunk_id": "p628-x14"})[0]
        checks.append(("C12 6장 밖 텍스트 인용", outside["internal_id"] == "p628-x14"
                       and outside["pdf_page"] == 628 and bool(outside["section_no"])))
        original_sources = api_main.SOURCES
        try:
            with TemporaryDirectory() as directory:
                api_main.SOURCES = Path(directory)
                table_image = client.get("/api/source/p629-t3.png")
                text_image = client.get("/api/source/p628-x14.png")
                checks.append(("C13 없는 PNG 즉석 생성", table_image.status_code == 200
                               and text_image.status_code == 200
                               and table_image.content.startswith(b"\x89PNG\r\n\x1a\n")
                               and text_image.content.startswith(b"\x89PNG\r\n\x1a\n")
                               and (Path(directory) / "p629-t3.png").is_file()
                               and (Path(directory) / "p628-x14.png").is_file()))
        finally:
            api_main.SOURCES = original_sources

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    print("쪽 대응 요약:", json.dumps(summarize(page_map)["offsets_by_division"], ensure_ascii=False))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

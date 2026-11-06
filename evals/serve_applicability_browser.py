"""Loopback-only server for Sol's manual browser verification of this hotfix.

This is NOT the production entrypoint and does not exercise auth, the real Postgres
chat store, usage-limit accounting, or any remote model/embedding call. It is a disposable
test server: thread state lives in an in-memory LangGraph MemorySaver (process memory only),
and search is pinned to a small deterministic fixture covering the scenarios already in
evals/check_applicability_hotfix.py and evals/check_multi_formwork_height.py (가설 계단,
합판거푸집, 레미콘). No test account is needed; there is no login.

It serves the real frontend/build (run `npm run build` first) and connects /api/chat,
/api/usage (static sample usage, not the real usage_limits module), and /api/export to the
actual dialogue_service.respond/restore/export_response + build_xlsx used in production —
only retrieval is pinned.

Start:
    PYTHONPATH=. AGENT_OFFLINE=1 AGENT_LLM=off AGENT_MODE=tools \
        .venv/Scripts/python.exe evals/serve_applicability_browser.py

Then open http://127.0.0.1:8765/ . Health/metadata: GET /api/health (always {"status":"ok"},
this process has no DB readiness to wait on) and GET /__meta (lists the mocked pieces).

Try: "가설 계단 견적" -> 높이 8 -> see BLOCKED + applicability scope -> "높이를 6m로 정정해줘"
-> 폭 0.9 -> PARTIAL. Or "합판거푸집 200㎡ 수직고 7m".
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend.agent.estimate import dialogue, tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402
from backend.api import dialogue_service  # noqa: E402
from backend.api.tables import build_xlsx, estimate_filename  # noqa: E402

PORT = int(os.environ.get("APPLICABILITY_BROWSER_PORT", "8765"))
BUILD_DIR = ROOT / "frontend" / "build"

SPECS = list(load_specs().values())
_FIXTURE_KEYWORDS = {
    "가설": ("공통", "2-7-7"), "계단": ("공통", "2-7-7"),
    "거푸집": ("공통", "6-3-1"),
    "레미콘": ("공통", "6-1-1"),
}


def _fixture_hit(query: str) -> dict | None:
    for keyword, (division, section_no) in _FIXTURE_KEYWORDS.items():
        if keyword in query:
            spec = next((s for s in SPECS if s["division"] == division and s["section_no"] == section_no), None)
            if spec:
                return {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
                        "section": f"{spec['section_no']} {spec['title']}", "page": 1, "table_id": None,
                        "text": spec["title"], "chunk_id": "mock", "ref": spec["id"]}
    return None


def _retrieve(state: dict) -> dict:
    hit = _fixture_hit(state.get("query", ""))
    return {"hits": [hit] if hit else [], "search_info": {"method": "mock-fixture", "api_calls": 0, "warnings": []}}


_PATCHES = [patch.object(tools, "retrieve", side_effect=_retrieve),
            patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None}))]
for p in _PATCHES:
    p.start()  # 프로세스 전체에서 유지한다(일회성 검증 서버이므로 stop하지 않음)

GRAPH = dialogue.build_dialogue_graph()
app = FastAPI(title="applicability-hotfix-browser-check")


@app.middleware("http")
async def _no_remote_connect(request: Request, call_next):
    # 원격 DB/API로 접속할 수 없게 connect-src를 이 서버 자신으로만 제한한다.
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "connect-src 'self'"
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/__meta")
def meta():
    return {"mocked": ["retrieve (deterministic keyword fixture, no embedding/model call)",
                        "citation page lookup (no PDF image store)"],
            "real": ["dialogue graph", "estimate/tools.py", "dialogue_service response conversion",
                     "xlsx export (build_xlsx)"],
            "not_covered": ["auth", "Postgres chat storage", "usage_limits accounting"],
            "fixture_keywords": list(_FIXTURE_KEYWORDS)}


@app.get("/api/usage")
def usage():
    # 운영 usage_limits 모듈을 쓰지 않는다(샘플 값). resets_at은 실제 현재시각+1일이어야 한다 —
    # 먼 미래의 고정값은 프런트의 남은시간 setTimeout 계산이 int32를 넘어 반복 GET을 유발할 수 있다.
    from datetime import datetime, timedelta, timezone
    resets_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    return {"limit": 9999, "used": 0, "remaining": 9999, "service_limit": 9999,
            "service_remaining": 9999, "resets_at": resets_at, "timezone": "Asia/Seoul"}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    thread_id = body.get("thread_id") or os.urandom(8).hex()
    try:
        result = dialogue_service.respond(GRAPH, thread_id, body)
    except Exception as exc:  # 테스트 서버: 운영과 달리 그대로 노출한다
        return JSONResponse({"status": "ERROR", "message": f"{type(exc).__name__}: {exc}"}, status_code=500)
    result["thread_id"] = thread_id
    return result


@app.get("/api/conversations/{thread_id}")
def restore(thread_id: str):
    try:
        result = dialogue_service.restore(GRAPH, thread_id)
    except Exception as exc:
        return JSONResponse({"status": "ERROR", "message": f"{type(exc).__name__}: {exc}"}, status_code=404)
    result["thread_id"] = thread_id
    return result


@app.get("/api/export/{thread_id}.xlsx")
def export_xlsx(thread_id: str):
    response = dialogue_service.export_response(GRAPH, thread_id)
    filename = estimate_filename(response)  # 이미 .xlsx로 끝난다 — 다시 붙이면 확장자가 중복된다
    from urllib.parse import quote
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii")
    return Response(build_xlsx(response),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'})


_TEST_SERVER_BANNER = (
    '<div style="position:fixed;top:0;left:0;right:0;z-index:99999;pointer-events:none;'
    'background:#b91c1c;color:#fff;font:600 13px sans-serif;text-align:center;'
    'padding:4px 0">TEST SERVER (in-memory, no auth/DB) — '
    'applicability-hotfix review build only</div>'
).encode("utf-8")


def _html_with_banner(path: Path) -> Response:
    html = path.read_bytes()
    marker = b"<body"
    idx = html.find(marker)
    if idx == -1:
        return FileResponse(path)
    end = html.find(b">", idx) + 1
    html = html[:end] + _TEST_SERVER_BANNER + html[end:]
    return Response(html, media_type="text/html")


if BUILD_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(BUILD_DIR / "static")), name="static")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # 경로 조작으로 BUILD_DIR 밖 파일을 서빙하지 않도록 resolve 후 상위 디렉터리인지 확인한다.
        candidate = (BUILD_DIR / full_path).resolve()
        if full_path and candidate.is_file() and BUILD_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        # index.html은 프리렌더된 홈("/")만, 그 외 모든 경로(/chat 포함)는 실제 앱 셸로 응답한다.
        shell = BUILD_DIR / ("index.html" if full_path in ("", "index.html") else "app-shell.html")
        return _html_with_banner(shell)
else:
    @app.get("/")
    def no_build():
        return JSONResponse({"error": "frontend/build가 없습니다. 먼저 `npm run build`를 실행하세요."}, status_code=503)


if __name__ == "__main__":
    import uvicorn
    print(f"[applicability-browser-check] http://127.0.0.1:{PORT}/  (in-memory, no auth/DB, retrieve is a fixture)")
    uvicorn.run(app, host="127.0.0.1", port=PORT)

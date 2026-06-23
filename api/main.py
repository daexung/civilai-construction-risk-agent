"""
건설 리스크 분석 API
- 프로젝트 관리
- 대화 관리
- 메시지 히스토리
- AI 에이전트 (router → weather/equipment/labor_cost/material)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, auth, projects, conversations, messages, chat

app = FastAPI(
    title="Construction Risk Agent API",
    description="건설 리스크 분석 API (날씨, 장비, 인건비, 자재)",
    version="1.0.0"
)

# CORS 설정 (프론트: localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(conversations.router)
app.include_router(messages.router)
app.include_router(chat.router)


@app.on_event("startup")
async def startup_event():
    """앱 시작 시 그래프 사전 로드 (첫 요청 지연 제거)"""
    print("[INFO] API started - Construction Risk Agent")
    try:
        from api.routers.chat import get_graph
        get_graph()
        print("[INFO] AI graph 로드 완료")
    except Exception as e:
        print(f"[WARN] AI graph 로드 실패 (요청 시 재시도됨): {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """앱 종료 시"""
    print("[INFO] API shutdown")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

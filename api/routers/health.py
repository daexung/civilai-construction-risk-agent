"""Health Check 라우터"""

from fastapi import APIRouter
from api.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """헬스체크"""
    return {"status": "ok"}

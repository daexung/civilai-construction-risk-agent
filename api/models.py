"""API 요청/응답 모델 (Pydantic)"""

from pydantic import BaseModel, Field
from typing import Any, Optional, List, Dict
from datetime import datetime


# ── Projects ──────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    site_name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    work_type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None


class Project(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Conversations ─────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: Optional[str] = "새로운 대화"


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1)


class Conversation(BaseModel):
    id: str
    project_id: Optional[str]
    owner_id: str
    owner_name: str
    title: str
    visibility: str
    can_write: bool
    message_count: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Messages ──────────────────────────────────────────────────────

class Message(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    final_response: Optional[str] = None
    structured_response: Optional[Dict[str, Any]] = None
    agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MessageList(BaseModel):
    messages: List[Message]


# ── Chat ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    content: str


# ── Health ────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str


# ── Members ───────────────────────────────────────────────────────

class MemberAddRequest(BaseModel):
    email: str = Field(..., min_length=1)
    role: str = "member"


# ── Auth ───────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class AuthResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    token: str

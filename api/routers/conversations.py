"""Conversations 라우터"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
import uuid

from api.database import get_db_cursor, dict_from_row
from api.models import ConversationCreate, ConversationUpdate, Conversation
from api.security import get_current_user

router = APIRouter(tags=["conversations"])

DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def _row_to_conversation(row: dict, current_user_id: str) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    d["project_id"] = str(d["project_id"]) if d.get("project_id") else None
    d["owner_id"] = str(d["owner_id"])
    d["can_write"] = (d["owner_id"] == current_user_id)
    d["message_count"] = d.get("message_count") or 0
    return d


# ── Quick Conversations (일반 대화) ──────────────────────────────

@router.get("/conversations/quick", response_model=list[Conversation])
async def list_quick_conversations(current_user: dict = Depends(get_current_user)):
    """내 빠른 질문 대화 목록"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT
                c.id, c.project_id, c.title, c.visibility,
                c.created_at, c.updated_at,
                c.owner_id, u.name AS owner_name,
                COUNT(m.id) AS message_count
            FROM conversations c
            JOIN users u ON u.id = c.owner_id
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.project_id = %s AND c.owner_id = %s
            GROUP BY c.id, u.name
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
        """, (DEFAULT_PROJECT_ID, current_user["user_id"]))
        rows = cursor.fetchall()
        return [_row_to_conversation(dict_from_row(r), current_user["user_id"]) for r in rows]


@router.post("/conversations/quick", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create_quick_conversation(
    req: ConversationCreate,
    current_user: dict = Depends(get_current_user),
):
    """빠른 질문 대화 생성"""
    conv_id = str(uuid.uuid4())
    now = datetime.utcnow()

    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO conversations (id, project_id, owner_id, title, visibility, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'private', %s, %s)
        """, (conv_id, DEFAULT_PROJECT_ID, current_user["user_id"], req.title, now, now))
        conn.commit()

        cursor.execute("""
            SELECT
                c.id, c.project_id, c.title, c.visibility,
                c.created_at, c.updated_at,
                c.owner_id, u.name AS owner_name,
                0 AS message_count
            FROM conversations c
            JOIN users u ON u.id = c.owner_id
            WHERE c.id = %s
        """, (conv_id,))
        row = cursor.fetchone()
        return _row_to_conversation(dict_from_row(row), current_user["user_id"])


# ── Project Conversations ────────────────────────────────────────

@router.get("/projects/{project_id}/conversations", response_model=list[Conversation])
async def list_project_conversations(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트의 대화 목록"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")

        cursor.execute("""
            SELECT
                c.id, c.project_id, c.title, c.visibility,
                c.created_at, c.updated_at,
                c.owner_id, u.name AS owner_name,
                COUNT(m.id) AS message_count
            FROM conversations c
            JOIN users u ON u.id = c.owner_id
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.project_id = %s
            GROUP BY c.id, u.name
            ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC
        """, (project_id,))
        rows = cursor.fetchall()
        return [_row_to_conversation(dict_from_row(r), current_user["user_id"]) for r in rows]


@router.post("/projects/{project_id}/conversations", response_model=Conversation, status_code=status.HTTP_201_CREATED)
async def create_project_conversation(
    project_id: str,
    req: ConversationCreate,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트 대화 생성"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")

        conv_id = str(uuid.uuid4())
        now = datetime.utcnow()
        cursor.execute("""
            INSERT INTO conversations (id, project_id, owner_id, title, visibility, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'project_shared', %s, %s)
        """, (conv_id, project_id, current_user["user_id"], req.title, now, now))
        conn.commit()

        cursor.execute("""
            SELECT
                c.id, c.project_id, c.title, c.visibility,
                c.created_at, c.updated_at,
                c.owner_id, u.name AS owner_name,
                0 AS message_count
            FROM conversations c
            JOIN users u ON u.id = c.owner_id
            WHERE c.id = %s
        """, (conv_id,))
        row = cursor.fetchone()
        return _row_to_conversation(dict_from_row(row), current_user["user_id"])


# ── Conversation Update / Delete ─────────────────────────────────

@router.patch("/conversations/{conv_id}", response_model=dict)
async def update_conversation(
    conv_id: str,
    req: ConversationUpdate,
    current_user: dict = Depends(get_current_user),
):
    """대화 제목 수정"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT owner_id FROM conversations WHERE id = %s", (conv_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(dict_from_row(row)["owner_id"]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        now = datetime.utcnow()
        cursor.execute("""
            UPDATE conversations SET title = %s, updated_at = %s WHERE id = %s
            RETURNING id, title
        """, (req.title, now, conv_id))
        conn.commit()
        return dict_from_row(cursor.fetchone())


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: str,
    current_user: dict = Depends(get_current_user),
):
    """대화 삭제"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT owner_id FROM conversations WHERE id = %s", (conv_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if str(dict_from_row(row)["owner_id"]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="권한이 없습니다")

        cursor.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
        conn.commit()

    return None

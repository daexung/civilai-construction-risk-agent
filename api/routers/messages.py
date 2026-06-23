"""Messages 라우터"""

from fastapi import APIRouter, HTTPException, status

from api.database import get_db_cursor, dict_from_row
from api.models import MessageList

router = APIRouter(tags=["messages"])


@router.get("/conversations/{conv_id}/messages", response_model=MessageList)
async def list_messages(conv_id: str):
    """메시지 목록 조회 (created_at 오름차순)"""
    with get_db_cursor() as (cursor, conn):
        # 대화 존재 확인
        cursor.execute("SELECT id FROM conversations WHERE id = %s", (conv_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 메시지 조회
        cursor.execute("""
            SELECT id, conversation_id, role, content, structured_response, agent, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
        """, (conv_id,))
        rows = cursor.fetchall()
        def to_msg(r):
            d = dict_from_row(r)
            created_at = d.get("created_at")
            if created_at and hasattr(created_at, "isoformat"):
                d["created_at"] = created_at.isoformat() + "Z"
            return {
                **d,
                "id": str(d["id"]),
                "conversation_id": str(d["conversation_id"]),
                "final_response": d["content"] if d.get("role") == "assistant" else None,
            }
        messages = [to_msg(r) for r in rows]
        return {"messages": messages}

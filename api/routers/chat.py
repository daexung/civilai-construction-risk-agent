"""Chat 라우터 (AI 에이전트 연동)"""

import os
import sys
from fastapi import APIRouter, HTTPException, status
from datetime import datetime
import uuid
from langchain_core.messages import HumanMessage, AIMessage
from psycopg2.extras import Json

from api.database import get_db_cursor, dict_from_row
from api.models import ChatRequest, Message

router = APIRouter(tags=["chat"])
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "20"))

# Graph 임포트 (라우터 담당자가 제공)
# TODO: 라우터 팀에서 graph 객체를 제공받으면 여기에 import
_graph = None


def get_graph():
    """Graph 객체 가져오기 (lazy loading)"""
    global _graph
    if _graph is None:
        try:
            # 라우터 폴더 경로 추가
            router_path = os.path.join(os.path.dirname(__file__), "..", "..", "agents", "router")
            if router_path not in sys.path:
                sys.path.insert(0, router_path)

            from graph import graph as lg_graph
            _graph = lg_graph
        except ImportError as e:
            raise RuntimeError(f"Failed to import graph: {e}")
    return _graph


@router.post("/conversations/{conv_id}/chat", response_model=Message)
def chat(conv_id: str, req: ChatRequest):
    """
    채팅 (핵심 엔드포인트)

    흐름:
    1. conversation 존재 확인 → project_id 추출
    2. 메시지 히스토리 조회
    3. LangChain 메시지로 변환
    4. graph.stream() 호출 (project_id 포함)
    5. AI 응답 저장 + 반환
    """
    with get_db_cursor() as (cursor, conn):
        # 1. Conversation 조회
        cursor.execute("""
            SELECT id, project_id FROM conversations WHERE id = %s
        """, (conv_id,))
        conv_row = cursor.fetchone()
        if not conv_row:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conv_dict = dict_from_row(conv_row)
        project_id = conv_dict["project_id"]

        # 2. 메시지 히스토리 조회
        cursor.execute("""
            SELECT role, content
            FROM (
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
            ) recent_messages
            ORDER BY created_at ASC, id ASC
        """, (conv_id, CHAT_HISTORY_LIMIT))
        msg_rows = cursor.fetchall()

        # 3. LangChain 메시지로 변환
        lc_messages = []
        for msg_row in msg_rows:
            msg_dict = dict_from_row(msg_row)
            if msg_dict["role"] == "user":
                lc_messages.append(HumanMessage(content=msg_dict["content"]))
            elif msg_dict["role"] == "assistant":
                lc_messages.append(AIMessage(content=msg_dict["content"]))
            else:
                print(f"[chat] Ignoring message with unknown role: {msg_dict['role']}")

        # 사용자 메시지 추가
        lc_messages.append(HumanMessage(content=req.content))

        # 4. Graph 호출
        try:
            graph = get_graph()
            ai_response_content = None
            structured_response = None

            for evt in graph.stream({
                "messages": lc_messages,
                "project_id": project_id  # ← 핵심! weather_node가 이 값 사용
            }, stream_mode="values"):
                # synthesize_node가 최종 응답을 final_response에 반환
                if evt.get("final_response"):
                    ai_response_content = evt["final_response"]
                if evt.get("structured_response"):
                    structured_response = evt["structured_response"]

            if not ai_response_content:
                raise RuntimeError("No AI response generated")

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI agent error: {str(e)}")

        # 5. 메시지 저장 (사용자 + AI)
        from datetime import timezone
        now = datetime.now(timezone.utc)

        # 사용자 메시지
        user_msg_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO messages (id, conversation_id, role, content, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_msg_id, conv_id, "user", req.content, now))

        # AI 응답 메시지
        ai_msg_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO messages (id, conversation_id, role, content, structured_response, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            ai_msg_id,
            conv_id,
            "assistant",
            ai_response_content,
            Json(structured_response) if structured_response is not None else None,
            now,
        ))

        conn.commit()

        return {
            "id": ai_msg_id,
            "conversation_id": conv_id,
            "role": "assistant",
            "content": ai_response_content,
            "final_response": ai_response_content,
            "structured_response": structured_response,
            "agent": None,
            "created_at": now.isoformat(),
        }

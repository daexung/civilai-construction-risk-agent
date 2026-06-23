"""Projects 라우터 (프로젝트 관리, 권한 체크 포함)"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
import uuid
from typing import Optional

from api.database import get_db_cursor, dict_from_row
from api.models import ProjectCreate, Project, MemberAddRequest
from api.security import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


def _check_project_member(cursor, project_id: str, user_id: str) -> bool:
    """사용자가 프로젝트의 멤버인지 확인"""
    cursor.execute(
        "SELECT id FROM project_members WHERE project_id = %s AND user_id = %s",
        (project_id, user_id),
    )
    return cursor.fetchone() is not None


def _check_project_owner(cursor, project_id: str, user_id: str) -> bool:
    """사용자가 프로젝트의 owner인지 확인"""
    cursor.execute(
        "SELECT id FROM project_members WHERE project_id = %s AND user_id = %s AND project_role = %s",
        (project_id, user_id, "owner"),
    )
    return cursor.fetchone() is not None


@router.get("", response_model=list[dict])
async def list_projects(current_user: dict = Depends(get_current_user)):
    """
    현재 사용자가 속한 프로젝트 목록 조회

    응답:
    ```json
    [
      {
        "id": "project-uuid",
        "name": "프로젝트명",
        "site_name": "현장명",
        "my_project_role": "owner"
      }
    ]
    ```
    """
    with get_db_cursor() as (cursor, conn):
        # 사용자가 속한 프로젝트 조회
        cursor.execute("""
            SELECT
                p.id,
                p.name,
                p.site_name,
                p.address,
                p.latitude,
                p.longitude,
                p.work_type,
                p.start_date,
                p.end_date,
                p.description,
                p.created_by,
                p.created_at,
                p.updated_at,
                pm.project_role as my_project_role
            FROM projects p
            INNER JOIN project_members pm ON p.id = pm.project_id
            WHERE pm.user_id = %s
            ORDER BY p.updated_at DESC
        """, (current_user["user_id"],))
        rows = cursor.fetchall()
        return [dict_from_row(r) for r in rows]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_project(req: ProjectCreate, current_user: dict = Depends(get_current_user)):
    """
    프로젝트 생성 (생성자가 자동으로 owner)

    요청:
    ```json
    {
      "name": "프로젝트명",
      "site_name": "현장명",
      "address": "주소",
      "latitude": 37.5665,
      "longitude": 126.978,
      "work_type": "철근콘크리트",
      "start_date": "2026-06-15",
      "end_date": "2026-08-30",
      "description": "설명"
    }
    ```
    """
    project_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with get_db_cursor() as (cursor, conn):
        # 프로젝트 생성
        cursor.execute("""
            INSERT INTO projects
            (id, name, site_name, address, latitude, longitude, work_type,
             start_date, end_date, description, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            project_id,
            req.name,
            getattr(req, "site_name", None),
            getattr(req, "address", None),
            getattr(req, "latitude", None),
            getattr(req, "longitude", None),
            getattr(req, "work_type", None),
            getattr(req, "start_date", None),
            getattr(req, "end_date", None),
            getattr(req, "description", None),
            current_user["user_id"],
            now,
            now,
        ))

        # 생성자를 owner로 등록
        member_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO project_members (id, project_id, user_id, project_role, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (member_id, project_id, current_user["user_id"], "owner", now))

        conn.commit()

        # 생성된 프로젝트 반환
        cursor.execute("""
            SELECT
                id, name, site_name, address, latitude, longitude,
                work_type, start_date, end_date, description,
                created_by, created_at, updated_at, 'owner' as my_project_role
            FROM projects WHERE id = %s
        """, (project_id,))
        row = cursor.fetchone()
        return dict_from_row(row)


@router.get("/{project_id}", response_model=dict)
async def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    프로젝트 상세 조회

    권한: 프로젝트 멤버만 조회 가능
    """
    with get_db_cursor() as (cursor, conn):
        # 멤버 확인
        if not _check_project_member(cursor, project_id, current_user["user_id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this project",
            )

        # 프로젝트 조회
        cursor.execute("""
            SELECT
                p.id, p.name, p.site_name, p.address, p.latitude, p.longitude,
                p.work_type, p.start_date, p.end_date, p.description,
                p.created_by, p.created_at, p.updated_at,
                pm.project_role as my_project_role
            FROM projects p
            INNER JOIN project_members pm ON p.id = pm.project_id
            WHERE p.id = %s AND pm.user_id = %s
        """, (project_id, current_user["user_id"]))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

        return dict_from_row(row)


@router.patch("/{project_id}", response_model=dict)
async def update_project(
    project_id: str,
    req: ProjectCreate,
    current_user: dict = Depends(get_current_user)
):
    """
    프로젝트 수정

    권한: owner만 수정 가능
    """
    with get_db_cursor() as (cursor, conn):
        # owner 확인
        if not _check_project_owner(cursor, project_id, current_user["user_id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project owner can update",
            )

        # 프로젝트 수정
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            UPDATE projects SET
                name = %s,
                site_name = %s,
                address = %s,
                latitude = %s,
                longitude = %s,
                work_type = %s,
                start_date = %s,
                end_date = %s,
                description = %s,
                updated_at = %s
            WHERE id = %s
        """, (
            req.name,
            getattr(req, "site_name", None),
            getattr(req, "address", None),
            getattr(req, "latitude", None),
            getattr(req, "longitude", None),
            getattr(req, "work_type", None),
            getattr(req, "start_date", None),
            getattr(req, "end_date", None),
            getattr(req, "description", None),
            now,
            project_id,
        ))
        conn.commit()

        # 수정된 프로젝트 반환
        cursor.execute("""
            SELECT
                p.id, p.name, p.site_name, p.address, p.latitude, p.longitude,
                p.work_type, p.start_date, p.end_date, p.description,
                p.created_by, p.created_at, p.updated_at,
                'owner' as my_project_role
            FROM projects p
            WHERE p.id = %s
        """, (project_id,))
        row = cursor.fetchone()
        return dict_from_row(row)


@router.get("/{project_id}/members", response_model=list[dict])
async def list_project_members(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트 멤버 목록 조회"""
    with get_db_cursor() as (cursor, conn):
        if not _check_project_member(cursor, project_id, current_user["user_id"]):
            raise HTTPException(status_code=403, detail="프로젝트 멤버가 아닙니다")

        cursor.execute("""
            SELECT u.id AS user_id, u.name, u.email, pm.project_role
            FROM project_members pm
            JOIN users u ON u.id = pm.user_id
            WHERE pm.project_id = %s
            ORDER BY pm.created_at ASC
        """, (project_id,))
        rows = cursor.fetchall()
        return [{**dict_from_row(r), "user_id": str(dict_from_row(r)["user_id"])} for r in rows]


@router.post("/{project_id}/members", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_project_member(
    project_id: str,
    req: MemberAddRequest,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트 멤버 초대 (owner만 가능)"""
    email = req.email
    role = req.role

    with get_db_cursor() as (cursor, conn):
        if not _check_project_owner(cursor, project_id, current_user["user_id"]):
            raise HTTPException(status_code=403, detail="owner만 멤버를 초대할 수 있습니다")

        cursor.execute("SELECT id, name, email FROM users WHERE email = %s", (email,))
        user_row = cursor.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="등록된 사용자를 찾을 수 없습니다")

        user = dict_from_row(user_row)
        user_id = str(user["id"])

        cursor.execute(
            "SELECT id FROM project_members WHERE project_id = %s AND user_id = %s",
            (project_id, user_id),
        )
        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="이미 프로젝트에 참여 중인 사용자입니다")

        member_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO project_members (id, project_id, user_id, project_role, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (member_id, project_id, user_id, role, now))
        conn.commit()

        return {"user_id": user_id, "name": user["name"], "email": user["email"], "project_role": role}


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """프로젝트 멤버 제거 (owner만 가능)"""
    with get_db_cursor() as (cursor, conn):
        if not _check_project_owner(cursor, project_id, current_user["user_id"]):
            raise HTTPException(status_code=403, detail="owner만 멤버를 제거할 수 있습니다")

        cursor.execute(
            "DELETE FROM project_members WHERE project_id = %s AND user_id = %s AND project_role != 'owner'",
            (project_id, user_id),
        )
        conn.commit()

    return None


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    프로젝트 삭제

    권한: owner만 삭제 가능
    """
    with get_db_cursor() as (cursor, conn):
        # owner 확인
        if not _check_project_owner(cursor, project_id, current_user["user_id"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project owner can delete",
            )

        # 프로젝트 삭제 (cascade로 project_members도 삭제됨)
        cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()

    return None

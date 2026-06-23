"""인증 라우터 (로그인, 사용자 정보 조회)"""

from fastapi import APIRouter, HTTPException, status, Depends
from api.database import get_db_cursor, dict_from_row
from api.models import LoginRequest, AuthResponse, UserResponse
from api.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """
    로그인 (이메일, 비밀번호)

    요청:
    ```json
    {
      "email": "user@example.com",
      "password": "password123"
    }
    ```

    응답:
    ```json
    {
      "user_id": "uuid",
      "name": "사용자명",
      "email": "user@example.com",
      "role": "user",
      "token": "jwt-token"
    }
    ```
    """
    with get_db_cursor() as (cursor, conn):
        # 사용자 조회
        cursor.execute(
            "SELECT id, name, email, password_hash, role FROM users WHERE email = %s",
            (req.email,),
        )
        user_row = cursor.fetchone()

        if not user_row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 잘못되었습니다",
            )

        user_dict = dict_from_row(user_row)

        # 비밀번호 검증
        if not verify_password(req.password, user_dict["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="이메일 또는 비밀번호가 잘못되었습니다",
            )

        # JWT 토큰 생성
        access_token = create_access_token(
            data={"user_id": str(user_dict["id"]), "role": user_dict["role"]}
        )

        return AuthResponse(
            user_id=str(user_dict["id"]),
            name=user_dict["name"],
            email=user_dict["email"],
            role=user_dict["role"],
            token=access_token,
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    현재 로그인한 사용자 정보 조회

    응답:
    ```json
    {
      "user_id": "uuid",
      "name": "사용자명",
      "email": "user@example.com",
      "role": "user"
    }
    ```
    """
    with get_db_cursor() as (cursor, conn):
        # 사용자 정보 조회
        cursor.execute(
            "SELECT id, name, email, role FROM users WHERE id = %s",
            (current_user["user_id"],),
        )
        user_row = cursor.fetchone()

        if not user_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다",
            )

        user_dict = dict_from_row(user_row)

        return UserResponse(
            user_id=str(user_dict["id"]),
            name=user_dict["name"],
            email=user_dict["email"],
            role=user_dict["role"],
        )

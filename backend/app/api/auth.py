"""用户认证（MVP mock）。

POST /api/v1/auth/login
  - 输入手机号即登录或注册（MVP 不发短信验证码）
  - 返回 user_id + token（token 直接等于 user_id 字符串）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import current_user
from app.db import get_db
from app.models import User, utcnow
from app.schemas import (
    LoginRequest,
    LoginResponse,
    MedicalInfoRequest,
    OkResponse,
    PeriodUpdateRequest,
    UserOut,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.phone == req.phone).first()
    is_new = False
    if not user:
        user = User(
            phone=req.phone,
            nickname=req.nickname or req.phone[-4:],
            last_check_in_at=utcnow(),  # 注册即视为已签到
            # 演示模式：60s 周期 + 30s 宽限期，便于看到预警递进
            check_in_period_seconds=60,
            grace_period_seconds=30,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new = True
    elif req.nickname and req.nickname != user.nickname:
        user.nickname = req.nickname
        db.commit()
        db.refresh(user)

    return LoginResponse(user_id=user.id, token=str(user.id), is_new=is_new)


users_router = APIRouter(prefix="/api/v1/users", tags=["users"])


@users_router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(current_user)) -> User:
    return user


@users_router.put("/me/period", response_model=UserOut)
def update_period(
    req: PeriodUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    user.check_in_period_seconds = req.check_in_period_seconds
    user.grace_period_seconds = req.grace_period_seconds
    db.commit()
    db.refresh(user)
    return user


@users_router.put("/me/medical", response_model=UserOut)
def update_medical(
    req: MedicalInfoRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    user.medical_info = req.model_dump(exclude_none=True)
    db.commit()
    db.refresh(user)
    return user


@users_router.delete("/me", response_model=OkResponse)
def delete_me(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> OkResponse:
    db.delete(user)
    db.commit()
    return OkResponse(message="account deleted")

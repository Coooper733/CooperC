"""共用 FastAPI 依赖。"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User


def current_user(
    x_user_token: str | None = Header(default=None, alias="X-User-Token"),
    db: Session = Depends(get_db),
) -> User:
    """MVP mock 鉴权：token 直接是 user_id。

    生产应换成 JWT / 短信验证码登录态。
    """
    if not x_user_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-User-Token header")
    try:
        user_id = int(x_user_token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user

"""事件流水：预警事件 + 通知日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import current_user
from app.db import get_db
from app.models import AlertEvent, NotificationLog, User
from app.schemas import AlertEventOut, NotificationOut

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("/alerts", response_model=list[AlertEventOut])
def list_alerts(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[AlertEvent]:
    return (
        db.query(AlertEvent)
        .filter(AlertEvent.user_id == user.id)
        .order_by(desc(AlertEvent.triggered_at))
        .limit(limit)
        .all()
    )


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[NotificationLog]:
    return (
        db.query(NotificationLog)
        .filter(NotificationLog.user_id == user.id)
        .order_by(desc(NotificationLog.sent_at))
        .limit(limit)
        .all()
    )

"""签到路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import current_user
from app.db import get_db
from app.models import (
    AlertEvent,
    AlertLevel,
    AlertResolution,
    AlertStatus,
    CheckIn,
    User,
    utcnow,
)
from app.schemas import CheckInOut, CheckInRequest, UserOut, UserStatusOut

router = APIRouter(prefix="/api/v1/checkin", tags=["checkin"])


@router.post("", response_model=CheckInOut)
def create_check_in(
    req: CheckInRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CheckIn:
    """一键签到。

    副作用：
    - 写入一条 CheckIn 记录
    - 更新 User.last_check_in_at
    - 重置 User.alert_level 为 NONE
    - 关闭所有该用户当前 ACTIVE 的 AlertEvent，标记为 SELF_CHECK_IN
    """
    now = utcnow()
    record = CheckIn(
        user_id=user.id,
        checked_in_at=now,
        source=req.source,
        location_lat=req.location_lat,
        location_lng=req.location_lng,
        note=req.note or "",
    )
    db.add(record)

    # 更新用户冗余字段
    user.last_check_in_at = now
    user.alert_level = AlertLevel.NONE
    user.alert_level_advanced_at = None

    # 关闭所有进行中的预警
    active_alerts = (
        db.query(AlertEvent)
        .filter(AlertEvent.user_id == user.id, AlertEvent.status == AlertStatus.ACTIVE)
        .all()
    )
    for alert in active_alerts:
        alert.status = AlertStatus.RESOLVED
        alert.resolution = AlertResolution.SELF_CHECK_IN
        alert.resolved_at = now
        alert.timeline = (alert.timeline or []) + [
            {"level": "resolved", "action": "self_check_in", "at": now.isoformat()}
        ]

    db.commit()
    db.refresh(record)
    return record


@router.get("/recent", response_model=list[CheckInOut])
def list_recent(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[CheckIn]:
    return (
        db.query(CheckIn)
        .filter(CheckIn.user_id == user.id)
        .order_by(desc(CheckIn.checked_in_at))
        .limit(limit)
        .all()
    )


status_router = APIRouter(prefix="/api/v1/status", tags=["status"])


@status_router.get("", response_model=UserStatusOut)
def my_status(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> UserStatusOut:
    """主页状态聚合：当前签到 / 预警 / SOS 状态。"""
    from app.models import SosEvent, SosStatus

    now = utcnow()
    last = user.last_check_in_at
    if last is None:
        seconds_since = None
        seconds_until = None
        is_overdue = False
    else:
        # 修正 timezone：SQLite 拿出来可能是 naive datetime
        if last.tzinfo is None:
            last = last.replace(tzinfo=now.tzinfo)
        seconds_since = int((now - last).total_seconds())
        seconds_until = user.check_in_period_seconds - seconds_since
        is_overdue = seconds_since > (user.check_in_period_seconds + user.grace_period_seconds)

    has_active_alert = (
        db.query(AlertEvent)
        .filter(AlertEvent.user_id == user.id, AlertEvent.status == AlertStatus.ACTIVE)
        .count() > 0
    )
    has_active_sos = (
        db.query(SosEvent)
        .filter(
            SosEvent.user_id == user.id,
            SosEvent.status.in_([SosStatus.PENDING, SosStatus.ACTIVE, SosStatus.ACKNOWLEDGED]),
        )
        .count() > 0
    )

    return UserStatusOut(
        user=UserOut.model_validate(user),
        seconds_since_last_check_in=seconds_since,
        seconds_until_overdue=seconds_until,
        is_overdue=is_overdue,
        has_active_alert=has_active_alert,
        has_active_sos=has_active_sos,
    )

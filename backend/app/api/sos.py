"""SOS 一键呼救路由。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core import notifier
from app.core.deps import current_user
from app.db import get_db
from app.models import (
    ContactStatus,
    EmergencyContact,
    SosEvent,
    SosStatus,
    User,
    utcnow,
)
from app.schemas import OkResponse, SosOut, SosTriggerRequest

router = APIRouter(prefix="/api/v1/sos", tags=["sos"])


@router.post("/trigger", response_model=SosOut, status_code=status.HTTP_201_CREATED)
def trigger_sos(
    req: SosTriggerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SosEvent:
    """触发 SOS。

    流程：
    1. 创建 SOS 事件，状态 PENDING，countdown_until = now + countdown_seconds
    2. 立即返回，前端展示倒计时
    3. 倒计时结束后由调度器扫描并 activate（或用户主动 cancel）
    """
    now = utcnow()
    sos = SosEvent(
        user_id=user.id,
        triggered_at=now,
        countdown_until=now + timedelta(seconds=req.countdown_seconds),
        source=req.source,
        status=SosStatus.PENDING,
        location_lat=req.location_lat,
        location_lng=req.location_lng,
        location_history=[],
    )
    if req.location_lat is not None and req.location_lng is not None:
        sos.location_history = [
            {"lat": req.location_lat, "lng": req.location_lng, "at": now.isoformat()}
        ]
    db.add(sos)
    db.commit()
    db.refresh(sos)

    # 立即给本人推送（提示倒计时已开始）
    notifier.send(
        db,
        user_id=user.id,
        channel="push",
        target="self",
        title="SOS 倒计时已开始",
        body=f"{req.countdown_seconds} 秒后将通知你的紧急联系人。如需取消请立即操作。",
        related_event_type="sos",
        related_event_id=sos.id,
    )
    return sos


@router.post("/{sos_id}/cancel", response_model=SosOut)
def cancel_sos(
    sos_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SosEvent:
    sos = db.query(SosEvent).filter(SosEvent.id == sos_id, SosEvent.user_id == user.id).first()
    if not sos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sos not found")
    if sos.status != SosStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"cannot cancel sos in status={sos.status.value}")
    sos.status = SosStatus.CANCELLED
    sos.ended_at = utcnow()
    sos.ended_by = "self"
    db.commit()
    db.refresh(sos)
    return sos


@router.post("/{sos_id}/end", response_model=SosOut)
def end_sos(
    sos_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> SosEvent:
    """用户标记自己已安全，终止 SOS。"""
    sos = db.query(SosEvent).filter(SosEvent.id == sos_id, SosEvent.user_id == user.id).first()
    if not sos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sos not found")
    if sos.status in (SosStatus.CANCELLED, SosStatus.ENDED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "sos already ended")

    now = utcnow()
    sos.status = SosStatus.ENDED
    sos.ended_at = now
    sos.ended_by = "self"
    db.commit()

    # 通知所有联系人：用户已安全
    contacts = (
        db.query(EmergencyContact)
        .filter(
            EmergencyContact.user_id == user.id,
            EmergencyContact.status == ContactStatus.ACCEPTED,
        )
        .all()
    )
    for c in contacts:
        notifier.send(
            db,
            user_id=user.id,
            channel="sms",
            target=c.contact_phone,
            title="安全确认",
            body=f"{user.nickname} 已确认安全，SOS 已解除。",
            related_event_type="sos",
            related_event_id=sos.id,
            commit=False,
        )
    db.commit()
    db.refresh(sos)
    return sos


@router.get("", response_model=list[SosOut])
def list_sos(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[SosEvent]:
    return (
        db.query(SosEvent)
        .filter(SosEvent.user_id == user.id)
        .order_by(desc(SosEvent.triggered_at))
        .limit(limit)
        .all()
    )

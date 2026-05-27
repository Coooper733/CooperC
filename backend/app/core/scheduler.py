"""预警调度引擎（核心）。

负责两件事：
1. 扫描所有用户，根据 last_check_in_at 推进多级预警 (NONE -> L1 -> L2 -> L3 -> L4)
2. 扫描 PENDING 状态的 SOS 事件，倒计时结束后激活并通知所有紧急联系人

设计原则：
- 状态机驱动：用户当前 alert_level 决定下一步动作
- 幂等：每次扫描只推进一级，不会跳级或重复发送
- 单事件聚合：同一次"超时事件"只创建一个 AlertEvent，多级预警在 timeline 中追加

演示模式：
- LEVEL_ADVANCE_SECONDS = 30s（每 30 秒推进一级），生产应改为 30 分钟
- TICK_INTERVAL_SECONDS = 5s（每 5 秒扫描），生产 60s 即可
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import notifier
from app.db import SessionLocal
from app.models import (
    AlertEvent,
    AlertLevel,
    AlertStatus,
    ContactStatus,
    EmergencyContact,
    SosEvent,
    SosStatus,
    User,
    UserStatus,
    utcnow,
)

logger = logging.getLogger("stillhere.scheduler")

# ---------------------------------------------------------------------------
# 配置（演示友好）
# ---------------------------------------------------------------------------

TICK_INTERVAL_SECONDS = 5
LEVEL_ADVANCE_SECONDS = 30  # 演示模式：每 30s 推进一级。生产建议 30 分钟。

# 多级预警的递进顺序
LEVEL_ORDER: list[AlertLevel] = [
    AlertLevel.NONE,
    AlertLevel.L1_USER_PUSH,
    AlertLevel.L2_USER_SMS,
    AlertLevel.L3_FIRST_CONTACT,
    AlertLevel.L4_ALL_CONTACTS,
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite 取出的 datetime 是 naive，统一补齐 UTC 时区。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _next_level(current: AlertLevel) -> AlertLevel | None:
    try:
        idx = LEVEL_ORDER.index(current)
    except ValueError:
        return AlertLevel.L1_USER_PUSH
    if idx >= len(LEVEL_ORDER) - 1:
        return None
    return LEVEL_ORDER[idx + 1]


def _get_or_create_active_alert(db: Session, user: User, now: datetime) -> AlertEvent:
    alert = (
        db.query(AlertEvent)
        .filter(AlertEvent.user_id == user.id, AlertEvent.status == AlertStatus.ACTIVE)
        .order_by(AlertEvent.triggered_at.desc())
        .first()
    )
    if alert is None:
        alert = AlertEvent(
            user_id=user.id,
            triggered_at=now,
            current_level=AlertLevel.L1_USER_PUSH,
            status=AlertStatus.ACTIVE,
            timeline=[],
        )
        db.add(alert)
        db.flush()  # 拿到 id
    return alert


# ---------------------------------------------------------------------------
# 多级预警动作
# ---------------------------------------------------------------------------


def _execute_level_actions(
    db: Session,
    user: User,
    alert: AlertEvent,
    level: AlertLevel,
    now: datetime,
) -> None:
    """根据预警级别执行对应的通知动作。"""
    timeline_entries: list[dict] = []

    if level == AlertLevel.L1_USER_PUSH:
        notifier.send(
            db,
            user_id=user.id,
            channel="push",
            target="self",
            title="你已超时未签到",
            body="如果你看到这条消息，请尽快打开 App 完成签到。",
            related_event_type="alert",
            related_event_id=alert.id,
            commit=False,
        )
        timeline_entries.append({"level": "l1", "action": "push_to_user", "at": now.isoformat()})

    elif level == AlertLevel.L2_USER_SMS:
        notifier.send(
            db, user_id=user.id, channel="sms", target=user.phone,
            title="紧急：长时间未签到",
            body=f"亲爱的{user.nickname}，你已长时间未签到，请尽快打开 App 完成签到，否则我们将通知你的紧急联系人。",
            related_event_type="alert", related_event_id=alert.id, commit=False,
        )
        notifier.send(
            db, user_id=user.id, channel="voice", target=user.phone,
            title="电话语音提醒",
            body="自动外呼用户本人，确认状态。",
            related_event_type="alert", related_event_id=alert.id, commit=False,
        )
        timeline_entries.append({"level": "l2", "action": "sms_voice_to_user", "at": now.isoformat()})

    elif level == AlertLevel.L3_FIRST_CONTACT:
        first = (
            db.query(EmergencyContact)
            .filter(
                EmergencyContact.user_id == user.id,
                EmergencyContact.status == ContactStatus.ACCEPTED,
            )
            .order_by(EmergencyContact.priority.asc(), EmergencyContact.id.asc())
            .first()
        )
        if first is None:
            timeline_entries.append({"level": "l3", "action": "no_contact_skipped", "at": now.isoformat()})
        else:
            notifier.send(
                db, user_id=user.id, channel="sms", target=first.contact_phone,
                title=f"{user.nickname} 长时间未签到",
                body=(
                    f"你的{first.relation or '亲友'}{user.nickname}已超过设定时间未签到死了么 App，"
                    f"请尽快联系本人确认安全。"
                ),
                related_event_type="alert", related_event_id=alert.id, commit=False,
            )
            timeline_entries.append({
                "level": "l3", "action": "notify_first_contact",
                "at": now.isoformat(), "target": first.contact_phone,
            })

    elif level == AlertLevel.L4_ALL_CONTACTS:
        contacts = (
            db.query(EmergencyContact)
            .filter(
                EmergencyContact.user_id == user.id,
                EmergencyContact.status == ContactStatus.ACCEPTED,
            )
            .order_by(EmergencyContact.priority.asc())
            .all()
        )
        if not contacts:
            timeline_entries.append({"level": "l4", "action": "no_contacts", "at": now.isoformat()})
        else:
            for c in contacts:
                notifier.send(
                    db, user_id=user.id, channel="sms", target=c.contact_phone,
                    title=f"【紧急】{user.nickname} 持续未响应",
                    body=(
                        f"{user.nickname}（{user.phone}）已多次提醒仍未签到，可能存在意外。"
                        f"请立即上门或拨打 110/120 协助查看。"
                    ),
                    related_event_type="alert", related_event_id=alert.id, commit=False,
                )
                notifier.send(
                    db, user_id=user.id, channel="voice", target=c.contact_phone,
                    title="紧急电话呼叫",
                    body=f"自动外呼联系人 {c.contact_name or c.contact_phone}",
                    related_event_type="alert", related_event_id=alert.id, commit=False,
                )
            timeline_entries.append({
                "level": "l4", "action": "notify_all_contacts",
                "at": now.isoformat(), "count": len(contacts),
            })

    # 追加时间线
    new_timeline = list(alert.timeline or []) + timeline_entries
    alert.timeline = new_timeline
    alert.current_level = level


# ---------------------------------------------------------------------------
# 主扫描逻辑
# ---------------------------------------------------------------------------


def _process_overdue_users(db: Session, now: datetime) -> None:
    users: Iterable[User] = db.execute(
        select(User).where(User.status == UserStatus.ACTIVE)
    ).scalars().all()

    for user in users:
        last = _aware(user.last_check_in_at)
        if last is None:
            continue

        seconds_since = (now - last).total_seconds()
        overdue_threshold = user.check_in_period_seconds + user.grace_period_seconds
        is_overdue = seconds_since > overdue_threshold

        if not is_overdue:
            # 用户已在宽限期内，正常状态。如果之前在预警中，应已被签到 API 重置。
            continue

        # 进入预警状态机
        current = user.alert_level or AlertLevel.NONE

        # 如果当前是 NONE，触发 L1
        if current == AlertLevel.NONE:
            target_level = AlertLevel.L1_USER_PUSH
        else:
            # 检查距离上次推进是否超过 LEVEL_ADVANCE_SECONDS
            advanced_at = _aware(user.alert_level_advanced_at)
            if advanced_at is None:
                continue  # 异常情况，跳过
            if (now - advanced_at).total_seconds() < LEVEL_ADVANCE_SECONDS:
                continue
            nxt = _next_level(current)
            if nxt is None:
                # 已到 L4，不再升级（持续等待联系人/用户响应）
                continue
            target_level = nxt

        # 创建或获取 active alert，执行级别动作
        alert = _get_or_create_active_alert(db, user, now)
        _execute_level_actions(db, user, alert, target_level, now)

        user.alert_level = target_level
        user.alert_level_advanced_at = now

        logger.info(
            "alert_advance user=%s phone=%s -> %s (overdue=%ss)",
            user.id, user.phone, target_level.value, int(seconds_since),
        )


def _process_pending_sos(db: Session, now: datetime) -> None:
    """倒计时结束后激活 SOS 并通知所有联系人。"""
    pending = (
        db.query(SosEvent)
        .filter(SosEvent.status == SosStatus.PENDING)
        .all()
    )
    for sos in pending:
        deadline = _aware(sos.countdown_until)
        if deadline is None or now < deadline:
            continue

        user = db.query(User).filter(User.id == sos.user_id).first()
        if not user:
            continue

        sos.status = SosStatus.ACTIVE
        sos.activated_at = now

        contacts = (
            db.query(EmergencyContact)
            .filter(
                EmergencyContact.user_id == user.id,
                EmergencyContact.status == ContactStatus.ACCEPTED,
            )
            .order_by(EmergencyContact.priority.asc())
            .all()
        )

        loc_text = ""
        if sos.location_lat is not None and sos.location_lng is not None:
            loc_text = f" 位置: {sos.location_lat:.6f},{sos.location_lng:.6f}"

        medical = user.medical_info or {}
        medical_summary = "; ".join(f"{k}={v}" for k, v in medical.items() if v) or "无"

        if not contacts:
            notifier.send(
                db, user_id=user.id, channel="push", target="self",
                title="SOS 已激活但无紧急联系人",
                body="请尽快添加联系人，或自行拨打 120/110。",
                related_event_type="sos", related_event_id=sos.id, commit=False,
            )
        else:
            for c in contacts:
                notifier.send(
                    db, user_id=user.id, channel="sms", target=c.contact_phone,
                    title=f"【SOS】{user.nickname} 紧急呼救",
                    body=(
                        f"{user.nickname}({user.phone}) 通过死了么 App 触发了 SOS。"
                        f"{loc_text} 医疗信息: {medical_summary}。"
                        f"请立即联系或前往救援，必要时拨打 120/110。"
                    ),
                    related_event_type="sos", related_event_id=sos.id, commit=False,
                )
                notifier.send(
                    db, user_id=user.id, channel="voice", target=c.contact_phone,
                    title="SOS 电话呼叫",
                    body=f"自动外呼 {c.contact_name or c.contact_phone}",
                    related_event_type="sos", related_event_id=sos.id, commit=False,
                )

        logger.warning(
            "sos_activated user=%s phone=%s contacts=%d",
            user.id, user.phone, len(contacts),
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def tick() -> None:
    """单次扫描（被 APScheduler 周期调用）。"""
    db = SessionLocal()
    try:
        now = utcnow()
        _process_pending_sos(db, now)
        _process_overdue_users(db, now)
        db.commit()
    except Exception:
        logger.exception("scheduler tick failed")
        db.rollback()
    finally:
        db.close()


_scheduler: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        tick,
        "interval",
        seconds=TICK_INTERVAL_SECONDS,
        id="stillhere_tick",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("scheduler started, tick=%ss, level_advance=%ss", TICK_INTERVAL_SECONDS, LEVEL_ADVANCE_SECONDS)
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

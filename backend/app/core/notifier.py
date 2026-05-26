"""通知抽象层。

MVP 阶段所有通知（推送/短信/电话/app 推送）都打到日志 + 写入 NotificationLog 表，
未来可在此处接入：
- 推送：APNs / FCM / 极光 / 个推
- 短信：阿里云 SMS / 腾讯云 SMS
- 电话语音：阿里云语音通知 / Twilio
"""
from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy.orm import Session

from app.models import NotificationLog

logger = logging.getLogger("stillhere.notifier")

Channel = Literal["push", "sms", "voice", "app"]


def send(
    db: Session,
    *,
    user_id: int,
    channel: Channel,
    target: str,
    title: str,
    body: str,
    related_event_type: str = "",
    related_event_id: int | None = None,
    commit: bool = True,
) -> NotificationLog:
    """发送一条通知（mock：写日志 + 持久化）。

    Args:
        user_id: 触发该通知的关联用户（即处于异常的本人）
        channel: 通知渠道
        target: 接收方电话号或 "self"
        commit: 是否在此函数内提交事务。调度器内部多条通知建议传 False，由调用方批量提交。
    """
    icon = {"push": "📱", "sms": "✉️", "voice": "📞", "app": "🔔"}.get(channel, "•")
    logger.warning(
        "%s [%s] -> %s | %s | %s | event=%s#%s",
        icon, channel.upper(), target, title, body, related_event_type, related_event_id,
    )

    record = NotificationLog(
        user_id=user_id,
        channel=channel,
        target=target,
        title=title,
        body=body,
        related_event_type=related_event_type,
        related_event_id=related_event_id,
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    return record

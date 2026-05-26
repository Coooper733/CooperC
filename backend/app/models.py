"""ORM 数据模型。

对应 PRD 第 6 章数据模型，MVP 阶段实现 6 张核心表。
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"   # 出差模式
    DELETED = "deleted"


class ContactStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REMOVED = "removed"


class CheckInSource(str, enum.Enum):
    MANUAL = "manual"
    WEARABLE = "wearable"
    AUTO = "auto"


class AlertLevel(str, enum.Enum):
    """多级预警等级。"""

    NONE = "none"          # 正常
    L1_USER_PUSH = "l1"    # 推送本人
    L2_USER_SMS = "l2"     # 短信+电话本人
    L3_FIRST_CONTACT = "l3"
    L4_ALL_CONTACTS = "l4"


class AlertStatus(str, enum.Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class AlertResolution(str, enum.Enum):
    SELF_CHECK_IN = "self_check_in"
    CONTACT_CONFIRMED = "contact_confirmed"
    SOS_CALLED = "sos_called"
    MANUAL_CANCEL = "manual_cancel"


class SosSource(str, enum.Enum):
    MANUAL = "manual"
    FALL = "fall"
    VOICE = "voice"


class SosStatus(str, enum.Enum):
    PENDING = "pending"        # 倒计时中
    CANCELLED = "cancelled"    # 用户取消
    ACTIVE = "active"          # 已发送给联系人
    ACKNOWLEDGED = "acknowledged"  # 联系人应答
    ENDED = "ended"            # 用户标记安全或超时


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_url: Mapped[str] = mapped_column(String(255), default="")

    # 签到周期，单位秒。MVP 演示模式默认 60s 便于快速触发预警。
    check_in_period_seconds: Mapped[int] = mapped_column(Integer, default=24 * 3600)
    grace_period_seconds: Mapped[int] = mapped_column(Integer, default=12 * 3600)

    # 紧急医疗信息（JSON：血型、过敏、慢性病、用药等）
    medical_info: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[UserStatus] = mapped_column(SAEnum(UserStatus), default=UserStatus.ACTIVE)

    # 当前最近一次签到时间（冗余字段，避免每次都查 check_ins 表）
    last_check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)

    # 当前预警等级（用于调度器推进多级预警）
    alert_level: Mapped[AlertLevel] = mapped_column(SAEnum(AlertLevel), default=AlertLevel.NONE)
    alert_level_advanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contacts: Mapped[list["EmergencyContact"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    check_ins: Mapped[list["CheckIn"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    alerts: Mapped[list["AlertEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sos_events: Mapped[list["SosEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 紧急联系人
# ---------------------------------------------------------------------------


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contact_phone: Mapped[str] = mapped_column(String(32))
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    relation: Mapped[str] = mapped_column(String(32), default="")
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 1=最优先
    status: Mapped[ContactStatus] = mapped_column(SAEnum(ContactStatus), default=ContactStatus.ACCEPTED)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="contacts")


# ---------------------------------------------------------------------------
# 签到记录
# ---------------------------------------------------------------------------


class CheckIn(Base):
    __tablename__ = "check_ins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[CheckInSource] = mapped_column(SAEnum(CheckInSource), default=CheckInSource.MANUAL)
    location_lat: Mapped[float | None] = mapped_column(nullable=True)
    location_lng: Mapped[float | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")

    user: Mapped[User] = relationship(back_populates="check_ins")


# ---------------------------------------------------------------------------
# 预警事件
# ---------------------------------------------------------------------------


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    current_level: Mapped[AlertLevel] = mapped_column(SAEnum(AlertLevel), default=AlertLevel.L1_USER_PUSH)
    status: Mapped[AlertStatus] = mapped_column(SAEnum(AlertStatus), default=AlertStatus.ACTIVE)
    resolution: Mapped[AlertResolution | None] = mapped_column(SAEnum(AlertResolution), nullable=True)

    # 多级预警时间线（数组，每条 {level, action, at, target}）
    timeline: Mapped[list] = mapped_column(JSON, default=list)

    user: Mapped[User] = relationship(back_populates="alerts")


# ---------------------------------------------------------------------------
# SOS 事件
# ---------------------------------------------------------------------------


class SosEvent(Base):
    __tablename__ = "sos_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    countdown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[SosSource] = mapped_column(SAEnum(SosSource), default=SosSource.MANUAL)
    status: Mapped[SosStatus] = mapped_column(SAEnum(SosStatus), default=SosStatus.PENDING)

    location_lat: Mapped[float | None] = mapped_column(nullable=True)
    location_lng: Mapped[float | None] = mapped_column(nullable=True)
    location_history: Mapped[list] = mapped_column(JSON, default=list)

    acknowledged_by_contact_id: Mapped[int | None] = mapped_column(ForeignKey("emergency_contacts.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by: Mapped[str] = mapped_column(String(64), default="")  # self / contact / timeout

    user: Mapped[User] = relationship(back_populates="sos_events")


# ---------------------------------------------------------------------------
# 通知日志（mock 存储，方便前端查看"发出去了什么"）
# ---------------------------------------------------------------------------


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(32))         # push / sms / voice / app
    target: Mapped[str] = mapped_column(String(128))         # phone or "self"
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(String(1024), default="")
    related_event_type: Mapped[str] = mapped_column(String(32), default="")  # alert / sos
    related_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

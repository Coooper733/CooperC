"""Pydantic API schemas（请求/响应模型）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    AlertLevel,
    AlertResolution,
    AlertStatus,
    CheckInSource,
    ContactStatus,
    SosSource,
    SosStatus,
    UserStatus,
)


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------


class OkResponse(BaseModel):
    ok: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)
    nickname: str | None = None


class LoginResponse(BaseModel):
    user_id: int
    token: str  # MVP: 直接返回 user_id 字符串作为 token
    is_new: bool


class PeriodUpdateRequest(BaseModel):
    check_in_period_seconds: int = Field(..., ge=10, le=7 * 24 * 3600)
    grace_period_seconds: int = Field(..., ge=0, le=24 * 3600)


class MedicalInfoRequest(BaseModel):
    blood_type: str | None = None
    allergies: str | None = None
    chronic_disease: str | None = None
    medications: str | None = None
    notes: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    nickname: str
    avatar_url: str
    check_in_period_seconds: int
    grace_period_seconds: int
    medical_info: dict[str, Any]
    status: UserStatus
    last_check_in_at: datetime | None
    alert_level: AlertLevel
    created_at: datetime


class UserStatusOut(BaseModel):
    """主页状态聚合：当前签到/预警状态 + 倒计时。"""

    user: UserOut
    seconds_since_last_check_in: int | None
    seconds_until_overdue: int | None     # 负数表示已超时
    is_overdue: bool
    has_active_alert: bool
    has_active_sos: bool


# ---------------------------------------------------------------------------
# 签到
# ---------------------------------------------------------------------------


class CheckInRequest(BaseModel):
    source: CheckInSource = CheckInSource.MANUAL
    note: str | None = None
    location_lat: float | None = None
    location_lng: float | None = None


class CheckInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    checked_in_at: datetime
    source: CheckInSource
    note: str


# ---------------------------------------------------------------------------
# 紧急联系人
# ---------------------------------------------------------------------------


class ContactCreateRequest(BaseModel):
    contact_phone: str = Field(..., min_length=4, max_length=32)
    contact_name: str = Field(default="", max_length=64)
    relation: str = Field(default="", max_length=32)
    priority: int = Field(default=1, ge=1, le=5)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_phone: str
    contact_name: str
    relation: str
    priority: int
    status: ContactStatus
    created_at: datetime


# ---------------------------------------------------------------------------
# SOS
# ---------------------------------------------------------------------------


class SosTriggerRequest(BaseModel):
    source: SosSource = SosSource.MANUAL
    location_lat: float | None = None
    location_lng: float | None = None
    countdown_seconds: int = Field(default=60, ge=0, le=120)


class SosOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    triggered_at: datetime
    countdown_until: datetime | None
    activated_at: datetime | None
    ended_at: datetime | None
    source: SosSource
    status: SosStatus
    location_lat: float | None
    location_lng: float | None
    ended_by: str


# ---------------------------------------------------------------------------
# 预警事件
# ---------------------------------------------------------------------------


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    triggered_at: datetime
    resolved_at: datetime | None
    current_level: AlertLevel
    status: AlertStatus
    resolution: AlertResolution | None
    timeline: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# 通知日志
# ---------------------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    target: str
    title: str
    body: str
    related_event_type: str
    related_event_id: int | None
    sent_at: datetime

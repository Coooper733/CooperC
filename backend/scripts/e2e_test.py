"""端到端测试脚本：验证签到 / 预警 / SOS 完整闭环。

不通过网络，直接用 FastAPI TestClient 调用应用，并手动驱动调度器 tick()。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

# 把 backend/ 加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.core import scheduler
from app.db import SessionLocal, init_db
from app.main import app
from app.models import User, utcnow


def hr(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main() -> None:
    init_db()

    with TestClient(app) as client:
        # 关闭后台调度器，改为手动 tick 便于断言
        scheduler.shutdown()

        # ------------------------------------------------------------------
        hr("1. 注册用户")
        r = client.post("/api/v1/auth/login", json={
            "phone": "13800138001",
            "nickname": "测试用户",
        })
        r.raise_for_status()
        login = r.json()
        token = login["token"]
        print(f"   user_id={login['user_id']}, is_new={login['is_new']}")
        H = {"X-User-Token": token}

        # ------------------------------------------------------------------
        hr("2. 设置短周期参数（演示模式）")
        client.put("/api/v1/users/me/period", headers=H, json={
            "check_in_period_seconds": 10,
            "grace_period_seconds": 5,
        }).raise_for_status()
        print("   period=10s, grace=5s（即 15 秒未签到进入预警）")

        # ------------------------------------------------------------------
        hr("3. 添加紧急联系人")
        for i, (phone, name, rel) in enumerate([
            ("13900139001", "妈妈", "母亲"),
            ("13900139002", "好友小明", "朋友"),
        ]):
            client.post("/api/v1/contacts", headers=H, json={
                "contact_phone": phone, "contact_name": name,
                "relation": rel, "priority": i + 1,
            }).raise_for_status()
            print(f"   ✓ {name} ({phone}) - {rel}")

        # ------------------------------------------------------------------
        hr("4. 第一次签到")
        r = client.post("/api/v1/checkin", headers=H, json={"source": "manual", "note": "起床啦"})
        r.raise_for_status()
        print(f"   ✓ 签到记录 id={r.json()['id']}")

        s = client.get("/api/v1/status", headers=H).json()
        assert not s["is_overdue"]
        assert s["user"]["alert_level"] == "none"
        print(f"   状态: 正常, 距下次截止 {s['seconds_until_overdue']}s")

        # ------------------------------------------------------------------
        hr("5. 把签到时间手动倒推 20 秒（模拟 20 秒未签到）")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == login["user_id"]).first()
            user.last_check_in_at = utcnow() - timedelta(seconds=20)
            db.commit()
        finally:
            db.close()
        print("   现在距上次签到 20s，超过 period(10) + grace(5) = 15s")

        # ------------------------------------------------------------------
        hr("6. 调度器 tick #1：应推进到 L1（推送本人）")
        scheduler.tick()
        s = client.get("/api/v1/status", headers=H).json()
        assert s["user"]["alert_level"] == "l1", f"got {s['user']['alert_level']}"
        assert s["has_active_alert"]
        notifs = client.get("/api/v1/events/notifications", headers=H).json()
        assert any(n["channel"] == "push" and n["target"] == "self" for n in notifs)
        print("   ✓ alert_level=l1, 已发送 push 给用户本人")

        # ------------------------------------------------------------------
        hr("7. tick #2：推进到 L2（短信+电话给本人）")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == login["user_id"]).first()
            user.alert_level_advanced_at = utcnow() - timedelta(seconds=scheduler.LEVEL_ADVANCE_SECONDS + 1)
            db.commit()
        finally:
            db.close()
        scheduler.tick()
        s = client.get("/api/v1/status", headers=H).json()
        assert s["user"]["alert_level"] == "l2"
        notifs = client.get("/api/v1/events/notifications", headers=H).json()
        assert any(n["channel"] == "sms" and n["target"] == "13800138001" for n in notifs)
        assert any(n["channel"] == "voice" and n["target"] == "13800138001" for n in notifs)
        print("   ✓ alert_level=l2, 已发送短信+语音给本人")

        # ------------------------------------------------------------------
        hr("8. 推进到 L3（通知第一紧急联系人 - 妈妈）")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == login["user_id"]).first()
            user.alert_level_advanced_at = utcnow() - timedelta(seconds=scheduler.LEVEL_ADVANCE_SECONDS + 1)
            db.commit()
        finally:
            db.close()
        scheduler.tick()
        s = client.get("/api/v1/status", headers=H).json()
        assert s["user"]["alert_level"] == "l3"
        notifs = client.get("/api/v1/events/notifications", headers=H).json()
        assert any(n["channel"] == "sms" and n["target"] == "13900139001" for n in notifs)
        print("   ✓ alert_level=l3, 已通知妈妈 (13900139001)")

        # ------------------------------------------------------------------
        hr("9. 推进到 L4（通知所有联系人）")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == login["user_id"]).first()
            user.alert_level_advanced_at = utcnow() - timedelta(seconds=scheduler.LEVEL_ADVANCE_SECONDS + 1)
            db.commit()
        finally:
            db.close()
        scheduler.tick()
        s = client.get("/api/v1/status", headers=H).json()
        assert s["user"]["alert_level"] == "l4"
        notifs = client.get("/api/v1/events/notifications", headers=H).json()
        assert any(n["channel"] == "sms" and n["target"] == "13900139002" for n in notifs)
        assert any(n["channel"] == "voice" and n["target"] == "13900139002" for n in notifs)
        print("   ✓ alert_level=l4, 已通知所有联系人")

        # ------------------------------------------------------------------
        hr("10. 用户回归补签 → 预警应被清除")
        client.post("/api/v1/checkin", headers=H, json={"source": "manual"}).raise_for_status()
        s = client.get("/api/v1/status", headers=H).json()
        assert s["user"]["alert_level"] == "none"
        assert not s["has_active_alert"]
        alerts = client.get("/api/v1/events/alerts", headers=H).json()
        latest = alerts[0]
        assert latest["status"] == "resolved"
        assert latest["resolution"] == "self_check_in"
        print(f"   ✓ 预警已解除, 时间线长度={len(latest['timeline'])} (l1/l2/l3/l4 + resolved)")

        # ------------------------------------------------------------------
        hr("11. 触发 SOS（10s 倒计时）")
        r = client.post("/api/v1/sos/trigger", headers=H, json={
            "source": "manual", "countdown_seconds": 10,
            "location_lat": 39.9042, "location_lng": 116.4074,
        })
        r.raise_for_status()
        sos = r.json()
        print(f"   sos_id={sos['id']}, status={sos['status']}")
        assert sos["status"] == "pending"

        scheduler.tick()
        sos_list = client.get("/api/v1/sos", headers=H).json()
        assert sos_list[0]["status"] == "pending"
        print("   ✓ tick 后仍 pending（倒计时未到），符合预期")

        # ------------------------------------------------------------------
        hr("12. 把 countdown_until 倒推让 SOS 立即激活")
        db = SessionLocal()
        try:
            from app.models import SosEvent
            s_event = db.query(SosEvent).filter(SosEvent.id == sos["id"]).first()
            s_event.countdown_until = utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        scheduler.tick()
        sos_list = client.get("/api/v1/sos", headers=H).json()
        assert sos_list[0]["status"] == "active"
        notifs = client.get("/api/v1/events/notifications", headers=H).json()
        sos_notifs = [n for n in notifs if n["related_event_type"] == "sos" and n["channel"] in ("sms", "voice")]
        assert len(sos_notifs) >= 4
        print(f"   ✓ SOS 激活, 通知联系人 {len(sos_notifs)} 条")

        # ------------------------------------------------------------------
        hr("13. 用户标记安全 → SOS 结束")
        r = client.post(f"/api/v1/sos/{sos['id']}/end", headers=H)
        r.raise_for_status()
        assert r.json()["status"] == "ended"
        print("   ✓ SOS 已结束，联系人收到安全确认")

        # ------------------------------------------------------------------
        hr("✅ 全部断言通过！完整闭环验证成功")


if __name__ == "__main__":
    main()

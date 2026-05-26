# 死了么 后端服务（MVP）

独居安全守护 App 的后端服务，包含签到、多级预警调度、SOS 呼救、紧急联系人管理。

## 快速开始

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> 需要 Python 3.10+，因为代码使用了 PEP 604 联合类型语法（`int | None`）。

访问：

- API 文档（Swagger）: http://localhost:8000/docs
- Web 演示前端: http://localhost:8000/
- 健康检查: http://localhost:8000/health

## 项目结构

```
backend/
├── app/
│   ├── main.py          # FastAPI 入口 + 静态资源
│   ├── db.py            # SQLAlchemy 连接 / Session
│   ├── models.py        # 数据模型
│   ├── schemas.py       # Pydantic API schema
│   ├── api/             # 路由
│   │   ├── auth.py      # mock 登录
│   │   ├── checkin.py   # 签到 + 状态聚合
│   │   ├── contacts.py  # 紧急联系人
│   │   ├── sos.py       # SOS 呼救
│   │   └── events.py    # 事件流水
│   └── core/
│       ├── scheduler.py # 预警调度引擎（核心）
│       ├── notifier.py  # 通知抽象（日志 mock）
│       └── deps.py      # 公共依赖
├── scripts/
│   └── e2e_test.py      # 端到端闭环测试
└── requirements.txt
```

## 核心调度逻辑

每 5 秒（演示用，生产建议 60 秒）扫描所有用户：

```
距上次签到 = now - last_check_in_at
T = check_in_period_seconds
W = grace_period_seconds（默认 12h，演示模式短得多）

if 距上次签到 > T + W:
    根据当前 alert_level 推进到下一级：
      L1: 推送（用户本人）
      L2: 短信+电话（用户本人）
      L3: 通知第 1 紧急联系人
      L4: 通知所有紧急联系人 + 上报最后位置
```

每级之间间隔 `LEVEL_ADVANCE_SECONDS`（演示 30s，生产 30 分钟）。

## 演示模式

新注册用户默认 `check_in_period_seconds=60`、`grace_period_seconds=30`，便于在 90 秒内看到完整预警链。
也可以通过 `PUT /api/v1/users/me/period` 进一步调小：

```json
{ "check_in_period_seconds": 10, "grace_period_seconds": 5 }
```

## 端到端测试

```bash
python scripts/e2e_test.py
```

该脚本通过 FastAPI TestClient 直接调用应用并手动驱动 `scheduler.tick()`，
完整验证：注册 → 签到 → 超时 → L1→L2→L3→L4 → 补签解除 → SOS 触发 → 激活 → 标记安全。

## 通知方式

MVP 阶段所有通知（短信、推送、电话）都打到日志 + 写入 `notification_logs` 表，便于演示。
未来接入：阿里云 SMS / APNs / FCM / 阿里云语音通知 / Twilio。

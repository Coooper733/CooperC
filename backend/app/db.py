"""数据库连接与会话管理。"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# SQLite 文件放在 backend/ 目录下，便于本地调试。
DB_PATH = Path(__file__).resolve().parent.parent / "stillhere.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 Session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """启动时初始化所有表。"""
    # 导入 models 触发 Base.metadata 注册
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

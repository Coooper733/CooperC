"""FastAPI 主应用。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import auth, checkin, contacts, events, sos
from app.core import scheduler
from app.db import init_db

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stillhere")


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    logger.info("StillHere backend started, version=%s", __version__)
    try:
        yield
    finally:
        scheduler.shutdown()
        logger.info("StillHere backend stopped")


app = FastAPI(
    title="死了么 / StillHere API",
    version=__version__,
    description="独居安全守护 App 后端服务（MVP）",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS（允许 web demo 同源访问；生产应限制）
# ---------------------------------------------------------------------------


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 路由挂载
# ---------------------------------------------------------------------------


app.include_router(auth.router)
app.include_router(auth.users_router)
app.include_router(checkin.router)
app.include_router(checkin.status_router)
app.include_router(contacts.router)
app.include_router(sos.router)
app.include_router(events.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


# ---------------------------------------------------------------------------
# Web demo 静态文件
# ---------------------------------------------------------------------------

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web-demo"

if WEB_DIR.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:
    @app.get("/")
    def index_missing() -> JSONResponse:
        return JSONResponse({"message": "web-demo directory not found", "api_docs": "/docs"})

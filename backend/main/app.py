"""Beacon API entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import AutoReconnect, NetworkTimeout, ServerSelectionTimeoutError

from backend.bot.lifecycle import start_bot_workers, stop_bot_workers
from backend.bot.routes import router as bot_router
from backend.trackers.crudl import router as trackers_router
from backend.website.crudl import router as website_router

from backend.tg.google_oauth import router as google_oauth_router
from backend.tg.routes.channel import router as tg_channel_router
from backend.tg.routes.client import router as tg_client_router
from backend.tg.routes.client_profile import router as tg_client_profile_router
from backend.tg.routes.report import router as tg_report_router
from backend.tg.routes.social import router as tg_social_router
from backend.tg.routes.tracker_sheet import router as tg_tracker_sheet_router
from backend.tg.routes.video import router as tg_video_router
from backend.tg.plug.routes import router as plug_router

from .compat import router as compat_router
from .config import cors_origin_list
from .db import close, ensure_indexes, ping, reset_client
from .main_crudl import router as main_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ping()
    ensure_indexes()
    # Local asset dirs used by social/video upload (TG parity)
    backend_root = Path(__file__).resolve().parents[1]
    for name in ("social_assets", "narration_cache", "reports"):
        (backend_root / name).mkdir(parents=True, exist_ok=True)
    # Must not block PORT bind — bot mongo init runs in a background task.
    bot_tasks: list = []
    try:
        bot_tasks = start_bot_workers()
    except Exception as error:  # noqa: BLE001 — Beacon must boot even if bot fails
        print(f"BOT: failed to schedule workers: {error}", flush=True)
    try:
        yield
    finally:
        await stop_bot_workers(bot_tasks)
        close()


app = FastAPI(title="Beacon", lifespan=lifespan)
_origins = cors_origin_list() or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AutoReconnect)
@app.exception_handler(NetworkTimeout)
@app.exception_handler(ServerSelectionTimeoutError)
async def mongo_transient_handler(_request: Request, exc: Exception):
    """Atlas TLS blips used to surface as opaque 500s — reset pool and ask client to retry."""
    reset_client()
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database temporarily unavailable ({exc.__class__.__name__}). Retry."},
    )

# Core auth / project CRUDL
app.include_router(main_router)

# TG Videos + Social parity (takes precedence for shared path names)
app.include_router(google_oauth_router)
app.include_router(tg_video_router)
app.include_router(tg_channel_router)
app.include_router(tg_client_router)
app.include_router(tg_client_profile_router)
app.include_router(tg_report_router)
app.include_router(tg_social_router)
app.include_router(tg_tracker_sheet_router)
app.include_router(plug_router)

# Beacon-native domains
app.include_router(website_router)
app.include_router(trackers_router)

# WhatsApp bot (Botify) — same logic/UI/DB under /bot/api/*
app.include_router(bot_router, prefix="/bot/api")

# Compat leftovers (doctor-ref / credentials / select aliases) — after TG so
# TG handlers win on overlapping client.* / social.* paths.
app.include_router(compat_router)

_assets = Path(__file__).resolve().parents[1] / "social_assets"
_assets.mkdir(parents=True, exist_ok=True)
app.mount("/social_assets", StaticFiles(directory=str(_assets)), name="social_assets")


@app.get("/")
def root():
    return {
        "name": "Beacon API",
        "health": "/health",
        "docs": "/docs",
        "frontend": "http://127.0.0.1:5173",
    }


@app.get("/health")
def health():
    return {"ok": True}

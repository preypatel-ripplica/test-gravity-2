from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routes import router
from services import expire_inactive_runs, drain_broadcasts, retry_failed_crm_pushes, sweep_call_recordings
from call_review_service import drain_call_reviews
from disposition_service import sync_all_dispositions


# How often the inactivity-timeout sweep runs. Kept short (60s) so timeouts fire
# close to their configured minute; the sweep itself is a cheap indexed query.
INACTIVITY_SWEEP_SECONDS = int(os.getenv("INACTIVITY_SWEEP_SECONDS", "60"))

# How often the broadcast worker drains pending recipients. Combined with
# BROADCAST_SENDS_PER_TICK (in services) this sets the outbound pace.
BROADCAST_TICK_SECONDS = int(os.getenv("BROADCAST_TICK_SECONDS", "5"))
# A call review is started by a button press, so it gets its own fast tick: the
# 60s inactivity heartbeat would make the button feel broken.
CALL_REVIEW_TICK_SECONDS = int(os.getenv("CALL_REVIEW_TICK_SECONDS", "5"))


async def _inactivity_sweep_loop():
    """Background heartbeat that closes chats gone silent mid-flow. Runs the
    (blocking, sync) sweep in a worker thread so it never stalls the event loop
    that serves webhooks and the SSE inbox."""
    tick = 0
    while True:
        await asyncio.sleep(INACTIVITY_SWEEP_SECONDS)
        tick += 1
        try:
            await asyncio.to_thread(expire_inactive_runs)
        except Exception as error:
            print(f"INACTIVITY SWEEP LOOP ERROR: {error}")

        # Same heartbeat pulls CRM call outcomes onto the lead sheet. Kept on a
        # separate try so a disposition problem can never stop chats being
        # closed - the timeout is the customer-facing half.
        try:
            await asyncio.to_thread(sync_all_dispositions)
        except Exception as error:
            print(f"DISPOSITION SYNC LOOP ERROR: {error}")

        # Roughly hourly: ask each CRM relay to re-push its "service unavailable"
        # failures (idempotent; timeouts excluded). 60 ticks x 60s = ~1h.
        if tick % 60 == 0:
            try:
                await asyncio.to_thread(retry_failed_crm_pushes)
            except Exception as error:
                print(f"CRM RETRY LOOP ERROR: {error}")

        # Every ~5 min: copy call recordings that failed to download, and link
        # calls whose clinic / conversation was not known when they arrived.
        if tick % 5 == 0:
            try:
                await asyncio.to_thread(sweep_call_recordings)
            except Exception as error:
                print(f"CALL RECORDING SWEEP ERROR: {error}")


async def _broadcast_worker_loop():
    """Drains running broadcasts in paced batches. Blocking sends run on a worker
    thread; pause/cancel are honored between sends inside drain_broadcasts."""
    while True:
        await asyncio.sleep(BROADCAST_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_broadcasts)
        except Exception as error:
            print(f"BROADCAST WORKER LOOP ERROR: {error}")


async def _call_review_loop():
    """Drains queued AI call reviews. The work is minutes long and must survive
    an instance dying, so the request only queues it and this loop runs it -
    any instance can pick up any job."""
    while True:
        await asyncio.sleep(CALL_REVIEW_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_call_reviews)
        except Exception as error:
            print(f"CALL REVIEW LOOP ERROR: {error}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sweep_task = asyncio.create_task(_inactivity_sweep_loop())
    broadcast_task = asyncio.create_task(_broadcast_worker_loop())
    review_task = asyncio.create_task(_call_review_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        broadcast_task.cancel()
        review_task.cancel()


app = FastAPI(title="WATI-like Workflow Bot Backend", lifespan=lifespan)

# Local dev origins are always allowed. In production (e.g. the frontend on its
# own Vercel domain) set ALLOWED_ORIGINS to a comma-separated list of origins,
# so the browser can call this backend cross-origin.
allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
allowed_origins += [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router)

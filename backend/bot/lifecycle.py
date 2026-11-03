"""Background workers from auto-whatsapp main.py — run inside Beacon lifespan."""

from __future__ import annotations

import asyncio
import os

from backend.bot.call_review_service import drain_call_reviews
from backend.bot.database import bot_mongo_configured, init_db
from backend.bot.disposition_service import sync_all_dispositions
from backend.bot.services import (
    drain_broadcasts,
    expire_inactive_runs,
    retry_failed_crm_pushes,
    sweep_call_recordings,
)

INACTIVITY_SWEEP_SECONDS = int(os.getenv("INACTIVITY_SWEEP_SECONDS", "60"))
BROADCAST_TICK_SECONDS = int(os.getenv("BROADCAST_TICK_SECONDS", "5"))
CALL_REVIEW_TICK_SECONDS = int(os.getenv("CALL_REVIEW_TICK_SECONDS", "5"))


async def _inactivity_sweep_loop():
    tick = 0
    while True:
        await asyncio.sleep(INACTIVITY_SWEEP_SECONDS)
        tick += 1
        try:
            await asyncio.to_thread(expire_inactive_runs)
        except Exception as error:
            print(f"INACTIVITY SWEEP LOOP ERROR: {error}", flush=True)
        try:
            await asyncio.to_thread(sync_all_dispositions)
        except Exception as error:
            print(f"DISPOSITION SYNC LOOP ERROR: {error}", flush=True)
        if tick % 60 == 0:
            try:
                await asyncio.to_thread(retry_failed_crm_pushes)
            except Exception as error:
                print(f"CRM RETRY LOOP ERROR: {error}", flush=True)
        if tick % 5 == 0:
            try:
                await asyncio.to_thread(sweep_call_recordings)
            except Exception as error:
                print(f"CALL RECORDING SWEEP ERROR: {error}", flush=True)


async def _broadcast_worker_loop():
    while True:
        await asyncio.sleep(BROADCAST_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_broadcasts)
        except Exception as error:
            print(f"BROADCAST WORKER LOOP ERROR: {error}", flush=True)


async def _call_review_loop():
    while True:
        await asyncio.sleep(CALL_REVIEW_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_call_reviews)
        except Exception as error:
            print(f"CALL REVIEW LOOP ERROR: {error}", flush=True)


async def _bot_supervisor() -> None:
    """Ping/indexes off the critical path so Cloud Run can bind PORT first."""
    try:
        await asyncio.to_thread(init_db)
    except Exception as error:  # noqa: BLE001
        print(
            f"BOT: init_db failed — background workers not started: {error}",
            flush=True,
        )
        return

    print("BOT: mongo ready — starting background workers", flush=True)
    workers = [
        asyncio.create_task(_inactivity_sweep_loop(), name="bot-inactivity"),
        asyncio.create_task(_broadcast_worker_loop(), name="bot-broadcast"),
        asyncio.create_task(_call_review_loop(), name="bot-call-review"),
    ]
    try:
        await asyncio.gather(*workers)
    except asyncio.CancelledError:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise


def start_bot_workers() -> list[asyncio.Task]:
    """Schedule bot init + loops without blocking lifespan (PORT bind).

    Returns the supervisor task list (possibly empty if MONGO_URI is unset).
    """
    if not bot_mongo_configured():
        print(
            "BOT: MONGO_URI not set — /bot/api is mounted but workers are disabled",
            flush=True,
        )
        return []
    return [asyncio.create_task(_bot_supervisor(), name="bot-supervisor")]


async def stop_bot_workers(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

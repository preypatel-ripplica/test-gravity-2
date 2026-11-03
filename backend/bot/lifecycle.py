"""Background workers from auto-whatsapp main.py — run inside Beacon lifespan."""

from __future__ import annotations

import asyncio
import os

from backend.bot.call_review_service import drain_call_reviews
from backend.bot.database import init_db
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
            print(f"INACTIVITY SWEEP LOOP ERROR: {error}")
        try:
            await asyncio.to_thread(sync_all_dispositions)
        except Exception as error:
            print(f"DISPOSITION SYNC LOOP ERROR: {error}")
        if tick % 60 == 0:
            try:
                await asyncio.to_thread(retry_failed_crm_pushes)
            except Exception as error:
                print(f"CRM RETRY LOOP ERROR: {error}")
        if tick % 5 == 0:
            try:
                await asyncio.to_thread(sweep_call_recordings)
            except Exception as error:
                print(f"CALL RECORDING SWEEP ERROR: {error}")


async def _broadcast_worker_loop():
    while True:
        await asyncio.sleep(BROADCAST_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_broadcasts)
        except Exception as error:
            print(f"BROADCAST WORKER LOOP ERROR: {error}")


async def _call_review_loop():
    while True:
        await asyncio.sleep(CALL_REVIEW_TICK_SECONDS)
        try:
            await asyncio.to_thread(drain_call_reviews)
        except Exception as error:
            print(f"CALL REVIEW LOOP ERROR: {error}")


def start_bot_workers() -> list[asyncio.Task]:
    """Init bot Mongo indexes and start background loops. Call from Beacon lifespan."""
    init_db()
    return [
        asyncio.create_task(_inactivity_sweep_loop()),
        asyncio.create_task(_broadcast_worker_loop()),
        asyncio.create_task(_call_review_loop()),
    ]


async def stop_bot_workers(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

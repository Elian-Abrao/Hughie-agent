from __future__ import annotations

import asyncio
import logging

from hughie.config import get_settings
from hughie.memory.maintenance import run_all

logger = logging.getLogger(__name__)

_maintenance_task: asyncio.Task | None = None


async def _maintenance_loop(interval_seconds: int) -> None:
    logger.info("Scheduler: maintenance loop started with interval=%ss", interval_seconds)
    try:
        while True:
            await asyncio.sleep(max(60, interval_seconds))
            await run_all()
    except asyncio.CancelledError:
        logger.info("Scheduler: maintenance loop cancelled")
        raise
    except Exception:
        logger.exception("Scheduler: maintenance loop failed")
        raise


def start_scheduler() -> asyncio.Task:
    global _maintenance_task
    if _maintenance_task and not _maintenance_task.done():
        return _maintenance_task

    settings = get_settings()
    _maintenance_task = asyncio.create_task(_maintenance_loop(settings.maintenance_interval_seconds))
    return _maintenance_task


async def stop_scheduler() -> None:
    global _maintenance_task
    if _maintenance_task is None:
        return
    _maintenance_task.cancel()
    try:
        await _maintenance_task
    except asyncio.CancelledError:
        pass
    _maintenance_task = None

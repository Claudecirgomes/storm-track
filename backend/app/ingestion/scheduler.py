"""Opt-in scheduler. Disabled by default and gate-checked on every cycle."""

import asyncio
import logging
from math import ceil

from backend.app.ingestion.service import run_enabled_products

logger = logging.getLogger("stormtrack.ingestion")


async def scheduler_loop(database_path, interval_seconds: int) -> None:
    while True:
        started = asyncio.get_running_loop().time()
        try:
            lookback_minutes = max(5, ceil(interval_seconds / 60) + 5)
            results = await asyncio.to_thread(
                run_enabled_products, database_path, lookback_minutes=lookback_minutes)
            for result in results:
                logger.info("collection cycle product=%s status=%s objects=%s",
                            result.get("product_id"), result.get("status"), result.get("objects_seen", 0))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("collection cycle failed")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0, interval_seconds - elapsed))

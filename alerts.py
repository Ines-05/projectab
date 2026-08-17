from __future__ import annotations

import asyncio
import logging
import os

from livekit.agents import AgentSession

import db

logger = logging.getLogger("speech.alerts")

POLL_INTERVAL_SECONDS = int(os.getenv("ALERT_POLL_INTERVAL_SECONDS", "60"))
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "5"))
EXPIRY_WARNING_DAYS = int(os.getenv("EXPIRY_WARNING_DAYS", "3"))


class AlertMonitor:
    """Periodically checks Supabase for low-stock/near-expiry products and speaks
    any new alert exactly once per session via session.generate_reply(), tracking
    already announced (product_id, reason) pairs in memory."""

    def __init__(self, session: AgentSession) -> None:
        self._session = session
        self._announced: set[tuple[str, str]] = set()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="inventory-alert-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("alert monitor task raised during shutdown")
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            try:
                await self._check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A single bad poll (e.g. transient Supabase error) must never
                # take down the call - log and try again next interval.
                logger.exception("alert monitor iteration failed; will retry next interval")

    async def _check_once(self) -> None:
        products = await asyncio.to_thread(
            db.get_low_stock_and_expiring, LOW_STOCK_THRESHOLD, EXPIRY_WARNING_DAYS
        )
        for product in products:
            reasons = product.get("alert_reasons", [])
            if "low_stock" in reasons:
                key = (product["id"], "low_stock")
                if key not in self._announced:
                    self._announced.add(key)
                    # Gemini Realtime sessions don't support session.say() (no
                    # separate TTS model to hand raw text to) - generate_reply
                    # with instructions is the equivalent for realtime models,
                    # same mechanism already used for the initial greeting.
                    await self._session.generate_reply(
                        instructions=(
                            f"Proactively tell the user, unprompted: {product['name']} "
                            f"is running low, only {product['stock_quantity']} left in stock."
                        )
                    )
            if "expiring" in reasons:
                key = (product["id"], "expiring")
                if key not in self._announced:
                    self._announced.add(key)
                    await self._session.generate_reply(
                        instructions=(
                            f"Proactively tell the user, unprompted: {product['name']} "
                            f"is expiring soon, on {product['expiration_date']}."
                        )
                    )

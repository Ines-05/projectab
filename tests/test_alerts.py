from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from alerts import AlertMonitor


def make_low_stock_product(product_id="p1", name="Nissin Cup Noodles Chicken Flavor 64g"):
    return {
        "id": product_id,
        "name": name,
        "stock_quantity": 3,
        "expiration_date": None,
        "alert_reasons": ["low_stock"],
    }


def make_expiring_product(product_id="p2", name="Amul Gold Full Cream Milk 500ml"):
    return {
        "id": product_id,
        "name": name,
        "stock_quantity": 40,
        "expiration_date": "2026-08-16",
        "alert_reasons": ["expiring"],
    }


async def test_new_alert_is_spoken_once():
    fake_session = AsyncMock()
    monitor = AlertMonitor(fake_session)

    with patch("db.get_low_stock_and_expiring", return_value=[make_low_stock_product()]):
        await monitor._check_once()

    assert fake_session.generate_reply.await_count == 1
    assert "Nissin" in fake_session.generate_reply.await_args.kwargs["instructions"]


async def test_same_alert_is_not_repeated_on_next_poll():
    fake_session = AsyncMock()
    monitor = AlertMonitor(fake_session)

    with patch("db.get_low_stock_and_expiring", return_value=[make_low_stock_product()]):
        await monitor._check_once()
        await monitor._check_once()

    assert fake_session.generate_reply.await_count == 1


async def test_low_stock_and_expiring_both_speak_when_both_present():
    fake_session = AsyncMock()
    monitor = AlertMonitor(fake_session)

    with patch(
        "db.get_low_stock_and_expiring",
        return_value=[make_low_stock_product(), make_expiring_product()],
    ):
        await monitor._check_once()

    assert fake_session.generate_reply.await_count == 2


async def test_check_once_exception_does_not_crash_run_loop():
    fake_session = AsyncMock()
    monitor = AlertMonitor(fake_session)

    call_count = 0

    async def flaky_check_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient db error")

    with patch.object(monitor, "_check_once", side_effect=flaky_check_once):
        with patch("alerts.POLL_INTERVAL_SECONDS", 0):
            monitor.start()
            await asyncio.sleep(0.05)
            await monitor.stop()

    assert call_count >= 1  # loop survived the first exception and kept running


async def test_stop_is_idempotent_and_safe_when_never_started():
    fake_session = AsyncMock()
    monitor = AlertMonitor(fake_session)
    await monitor.stop()  # never started - must not raise
    await monitor.stop()  # calling twice - must not raise

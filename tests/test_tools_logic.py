from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

import db
from tools import InventoryAssistant
from video import FrameBuffer


def make_assistant():
    room = MagicMock()
    room.local_participant.publish_data = AsyncMock()
    return InventoryAssistant(FrameBuffer(), room)


def make_match(name="Coca-Cola Classic 500ml", similarity=0.9, **overrides):
    match = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": name,
        "category": "drink",
        "stock_quantity": 60,
        "expiration_date": "2027-02-01",
        "similarity": similarity,
    }
    match.update(overrides)
    return match


async def test_get_product_stock_zero_matches_raises_clean_tool_error():
    assistant = make_assistant()
    with patch("db.match_product", return_value=[]):
        with pytest.raises(ToolError, match="couldn't find"):
            await assistant.get_product_stock(None, "nonexistent product")


async def test_get_product_stock_ambiguous_matches_raises_clean_tool_error():
    assistant = make_assistant()
    matches = [make_match("Snickers Peanut Chocolate Bar 51g", 0.85),
               make_match("Snickers King Size 93g", 0.83)]
    with patch("db.match_product", return_value=matches):
        with pytest.raises(ToolError, match="more than one close match"):
            await assistant.get_product_stock(None, "snickers")


async def test_get_product_stock_clean_single_match_returns_dict():
    assistant = make_assistant()
    matches = [make_match(similarity=0.9), make_match("Something else", 0.2)]
    with patch("db.match_product", return_value=matches):
        result = await assistant.get_product_stock(None, "coke")
    assert result == {
        "matched_name": "Coca-Cola Classic 500ml",
        "category": "drink",
        "stock_quantity": 60,
        "expiration_date": "2027-02-01",
    }


async def test_record_sale_insufficient_stock_becomes_tool_error():
    assistant = make_assistant()
    with patch("db.match_product", return_value=[make_match()]):
        with patch("db.record_sale", side_effect=db.InsufficientStockError("only 2 left")):
            with pytest.raises(ToolError, match="only 2 left"):
                await assistant.record_sale(None, "coke", 5)


async def test_record_sale_not_found_becomes_tool_error():
    assistant = make_assistant()
    with patch("db.match_product", return_value=[make_match()]):
        with patch("db.record_sale", side_effect=db.ProductNotFoundError("gone")):
            with pytest.raises(ToolError, match="gone"):
                await assistant.record_sale(None, "coke", 1)


async def test_record_sale_unexpected_db_error_becomes_generic_tool_error():
    assistant = make_assistant()
    with patch("db.match_product", return_value=[make_match()]):
        with patch("db.record_sale", side_effect=db.DbError("boom")):
            with pytest.raises(ToolError, match="Something went wrong"):
                await assistant.record_sale(None, "coke", 1)


async def test_record_sale_rejects_non_positive_quantity():
    assistant = make_assistant()
    with pytest.raises(ToolError, match="positive whole number"):
        await assistant.record_sale(None, "coke", 0)


async def test_record_sale_success_returns_updated_stock():
    assistant = make_assistant()
    with patch("db.match_product", return_value=[make_match()]):
        with patch("db.record_sale", return_value={"name": "Coca-Cola Classic 500ml", "stock_quantity": 58}):
            result = await assistant.record_sale(None, "coke", 2)
    assert result == {"matched_name": "Coca-Cola Classic 500ml", "remaining_stock": 58}


async def test_identify_product_no_frame_raises_tool_error():
    assistant = make_assistant()
    with patch("tools.CAMERA_WARMUP_TIMEOUT_SECONDS", 0.01):
        with patch("tools.CAMERA_WARMUP_POLL_INTERVAL_SECONDS", 0.01):
            with pytest.raises(ToolError, match="camera"):
                await assistant.identify_product(None)


async def test_identify_product_signals_client_to_enable_camera_when_no_frame():
    assistant = make_assistant()
    with patch("tools.CAMERA_WARMUP_TIMEOUT_SECONDS", 0.01):
        with patch("tools.CAMERA_WARMUP_POLL_INTERVAL_SECONDS", 0.01):
            with pytest.raises(ToolError):
                await assistant.identify_product(None)
    assistant._room.local_participant.publish_data.assert_called_once_with(
        "enable_camera", topic="camera-control"
    )


async def test_query_inventory_rejects_unsafe_sql():
    assistant = make_assistant()
    with patch("nl2sql.translate_to_sql", return_value="delete from products"):
        with pytest.raises(ToolError, match="can't run that one"):
            await assistant.query_inventory(None, "delete everything")


async def test_query_inventory_returns_rows_for_safe_sql():
    assistant = make_assistant()
    with patch("nl2sql.translate_to_sql", return_value="select name from products"):
        with patch("db.execute_readonly_query", return_value=[{"name": "Coca-Cola Classic 500ml"}]):
            result = await assistant.query_inventory(None, "list products")
    assert result == {"rows": [{"name": "Coca-Cola Classic 500ml"}]}

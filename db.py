from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, TypedDict

from postgrest.exceptions import APIError
from supabase import Client, create_client


class ProductMatch(TypedDict):
    id: str
    name: str
    category: str | None
    stock_quantity: int
    expiration_date: str | None
    similarity: float


class DbError(RuntimeError):
    """Base class for db-layer errors surfaced to tools.py."""


class ProductNotFoundError(DbError):
    pass


class InsufficientStockError(DbError):
    pass


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def match_product(search_term: str, threshold: float = 0.3, limit: int = 5) -> list[ProductMatch]:
    """Fuzzy-match a free-text product description against the products table."""
    resp = get_client().rpc(
        "match_product",
        {"search_term": search_term, "match_threshold": threshold, "match_count": limit},
    ).execute()
    return resp.data or []


def record_sale(product_id: str, quantity: int) -> dict[str, Any]:
    """Atomically record a sale and decrement stock via the record_sale() RPC."""
    try:
        resp = get_client().rpc(
            "record_sale", {"p_product_id": product_id, "p_quantity": quantity}
        ).execute()
    except APIError as exc:
        message = exc.message or str(exc)
        if "Insufficient stock" in message:
            raise InsufficientStockError(message) from exc
        if "was not found" in message:
            raise ProductNotFoundError(message) from exc
        raise DbError(message) from exc
    return resp.data[0]  # {"id", "name", "stock_quantity"}


def get_low_stock_and_expiring(stock_threshold: int, expiry_days: int) -> list[dict[str, Any]]:
    """Products under the stock threshold or expiring within expiry_days, each
    tagged with 'alert_reasons' (subset of {"low_stock", "expiring"})."""
    client = get_client()
    cutoff = (date.today() + timedelta(days=expiry_days)).isoformat()

    low_stock_rows = (
        client.table("products").select("*").lte("stock_quantity", stock_threshold).execute().data
    )
    expiring_rows = (
        client.table("products")
        .select("*")
        .not_.is_("expiration_date", "null")
        .lte("expiration_date", cutoff)
        .execute()
        .data
    )

    by_id: dict[str, dict[str, Any]] = {}
    for row in low_stock_rows:
        by_id.setdefault(row["id"], {**row, "alert_reasons": []})["alert_reasons"].append("low_stock")
    for row in expiring_rows:
        entry = by_id.setdefault(row["id"], {**row, "alert_reasons": []})
        entry["alert_reasons"].append("expiring")
    return list(by_id.values())


def execute_readonly_query(sql: str) -> list[dict[str, Any]]:
    """Run an LLM-generated read-only query via the execute_readonly_query RPC.

    Defense in depth: the RPC itself runs as a role with only SELECT grants,
    so a query that slips past nl2sql.is_safe_select() still can't write.
    """
    try:
        resp = get_client().rpc("execute_readonly_query", {"query": sql}).execute()
    except APIError as exc:
        raise DbError(exc.message or str(exc)) from exc
    return resp.data or []

from __future__ import annotations

import psycopg
import pytest

from nl2sql import is_safe_select


@pytest.mark.parametrize(
    "sql",
    [
        "select * from products",
        "SELECT count(*) FROM products WHERE stock_quantity < 5",
        "with low as (select * from products where stock_quantity < 5) select * from low",
        "  select name from products  ",
    ],
)
def test_is_safe_select_accepts_plain_selects(sql):
    assert is_safe_select(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "insert into products (name) values ('x')",
        "update products set stock_quantity = 0",
        "delete from products",
        "drop table products",
        "alter table products add column x text",
        "truncate products",
        "grant select on products to public",
        "select * from products; drop table products",
        "select * from products; select * from sales",
        "",
        "   ",
    ],
)
def test_is_safe_select_rejects_writes_ddl_and_stacked_statements(sql):
    assert is_safe_select(sql) is False


def test_execute_readonly_query_rpc_returns_rows(db_conn):
    result = db_conn.execute(
        "select execute_readonly_query(%s)",
        ("select name, stock_quantity from products where stock_quantity < 5",),
    ).fetchone()[0]
    names = {row["name"] for row in result}
    assert "Nissin Cup Noodles Chicken Flavor 64g" in names


def test_execute_readonly_query_rpc_blocks_data_modifying_cte(db_conn):
    """Deliberately bypasses the text-level guard to prove a second, structural
    layer of defense: execute_readonly_query wraps every query as a subquery
    (select ... from (%s) t), and Postgres itself refuses to nest a
    data-modifying WITH inside a subquery ("must be at the top level") -
    so this bypass attempt is rejected before transaction_read_only even
    comes into play. Either layer alone would stop this; both do."""
    before_count = db_conn.execute("select count(*) from products").fetchone()[0]

    with pytest.raises(psycopg.errors.FeatureNotSupported):
        db_conn.execute(
            "select execute_readonly_query(%s)",
            ("with deleted as (delete from products returning *) select * from deleted",),
        )

    after_count = db_conn.execute("select count(*) from products").fetchone()[0]
    assert after_count == before_count


def test_execute_readonly_query_rpc_blocks_function_call_bypass(db_conn):
    """The realistic bypass this guards against: a syntactically read-only
    "SELECT some_function(...)" that actually performs a write internally
    (record_sale decrements stock). Text filtering alone can't catch this -
    it's a plain SELECT - so the fix is the engine-level read-only transaction
    inside execute_readonly_query, which blocks the write regardless of what
    function performs it or what role/grants are involved."""
    product = db_conn.execute(
        "select id, stock_quantity from products where name = 'Coca-Cola Classic 500ml'"
    ).fetchone()

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        db_conn.execute(
            "select execute_readonly_query(%s)",
            (f"select record_sale('{product[0]}', 1)",),
        )

    stock_after = db_conn.execute(
        "select stock_quantity from products where id = %s", (product[0],)
    ).fetchone()[0]
    assert stock_after == product[1]

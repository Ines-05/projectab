from __future__ import annotations

import threading

import psycopg
from psycopg.rows import dict_row


def test_schema_applies_and_seeds_17_products(db_conn):
    rows = db_conn.execute("select count(*) from products").fetchone()
    assert rows[0] == 17

    extensions = {r[0] for r in db_conn.execute("select extname from pg_extension").fetchall()}
    assert "pg_trgm" in extensions

    tables = {r[0] for r in db_conn.execute(
        "select tablename from pg_tables where schemaname = 'public'"
    ).fetchall()}
    assert {"products", "sales"} <= tables


def test_schema_reapply_is_idempotent(db_conn, postgres_container):
    from pathlib import Path
    schema_sql = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text()

    db_conn.execute(schema_sql)  # re-apply on top of the already-applied schema

    count = db_conn.execute("select count(*) from products").fetchone()[0]
    assert count == 17  # on conflict (name) do nothing => no duplicates


def test_match_product_ranks_intended_result_first(db_conn):
    db_conn.row_factory = dict_row

    # NB: "coke" is deliberately not used here - it's a genuine near-tie
    # against this catalog (word_similarity ties at 0.4 with "Oreo Original
    # Sandwich Cookies 137g"), which in the real system correctly triggers
    # tools.py's ambiguity check rather than a silent wrong match - not a bug,
    # but a poor choice for an "unambiguous top match" test.
    row = db_conn.execute(
        "select * from match_product(%s) limit 1", ("coca cola classic",)
    ).fetchone()
    assert row is not None
    assert "Coca-Cola" in row["name"]

    row = db_conn.execute(
        "select * from match_product(%s) limit 1", ("a snickers chocolate bar",)
    ).fetchone()
    assert row is not None
    assert "Snickers" in row["name"]

    row = db_conn.execute(
        "select * from match_product(%s) limit 1", ("nescaffe",)
    ).fetchone()
    assert row is not None
    assert "Nescafe" in row["name"]


def test_match_product_returns_empty_for_gibberish(db_conn):
    rows = db_conn.execute(
        "select * from match_product(%s)", ("xyzzy not a real product at all",)
    ).fetchall()
    assert rows == []


def test_record_sale_decrements_stock_and_inserts_row(db_conn):
    db_conn.row_factory = dict_row
    product = db_conn.execute(
        "select id, stock_quantity from products where name = %s",
        ("Coca-Cola Classic 500ml",),
    ).fetchone()

    result = db_conn.execute(
        "select * from record_sale(%s, %s)", (product["id"], 5)
    ).fetchone()
    assert result["stock_quantity"] == product["stock_quantity"] - 5

    sales_count = db_conn.execute(
        "select count(*) as n from sales where product_id = %s", (product["id"],)
    ).fetchone()["n"]
    assert sales_count == 1


def test_record_sale_rejects_overselling_and_leaves_stock_unchanged(db_conn, postgres_container):
    db_conn.row_factory = dict_row
    product = db_conn.execute(
        "select id, stock_quantity from products where name = %s",
        ("Nissin Cup Noodles Chicken Flavor 64g",),
    ).fetchone()
    assert product["stock_quantity"] == 3

    try:
        db_conn.execute("select * from record_sale(%s, %s)", (product["id"], 999))
        raised = False
    except psycopg.Error:
        raised = True
        db_conn.rollback()

    assert raised

    with psycopg.connect(postgres_container, autocommit=True) as fresh_conn:
        stock_after = fresh_conn.execute(
            "select stock_quantity from products where id = %s", (product["id"],)
        ).fetchone()[0]
    assert stock_after == 3


def test_record_sale_serializes_concurrent_sales(db_conn, postgres_container):
    """Two concurrent sales against stock=1 should yield exactly one success
    and one failure, proving the row lock actually prevents a race rather
    than merely 'usually' working."""
    db_conn.execute(
        "update products set stock_quantity = 1 where name = 'Kleenex Facial Tissues 160ct'"
    )
    product_id = db_conn.execute(
        "select id from products where name = 'Kleenex Facial Tissues 160ct'"
    ).fetchone()[0]

    results = []

    def attempt_sale():
        try:
            with psycopg.connect(postgres_container, autocommit=True) as conn:
                conn.execute("select * from record_sale(%s, %s)", (product_id, 1))
            results.append("success")
        except psycopg.Error:
            results.append("failure")

    threads = [threading.Thread(target=attempt_sale) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["failure", "success"]

    with psycopg.connect(postgres_container, autocommit=True) as conn:
        final_stock = conn.execute(
            "select stock_quantity from products where id = %s", (product_id,)
        ).fetchone()[0]
    assert final_stock == 0

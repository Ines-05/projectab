from __future__ import annotations

import subprocess
import time
from pathlib import Path

import psycopg
import pytest

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
CONTAINER_NAME = "speech-agent-test-pg"
HOST_PORT = 55432


@pytest.fixture(scope="session")
def postgres_container():
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", CONTAINER_NAME,
            "-e", "POSTGRES_PASSWORD=test",
            "-p", f"{HOST_PORT}:5432",
            "postgres:17",
        ],
        check=True,
        capture_output=True,
    )
    dsn = f"host=localhost port={HOST_PORT} dbname=postgres user=postgres password=test"
    try:
        _wait_for_postgres(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


def _wait_for_postgres(dsn: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("select 1")
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"postgres container did not become ready in time: {last_error}")


@pytest.fixture()
def db_conn(postgres_container):
    """A fresh connection with the schema applied and rolled back after each test."""
    with psycopg.connect(postgres_container, autocommit=True) as conn:
        conn.execute(SCHEMA_PATH.read_text())
        yield conn
        conn.execute("drop schema public cascade; create schema public;")
        conn.execute("drop role if exists readonly_query_role;")

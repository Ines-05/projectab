from __future__ import annotations

import os
import re
from functools import lru_cache

from google import genai

SCHEMA_DESCRIPTION = """\
products(
    id uuid,
    name text,
    category text,
    stock_quantity integer,
    expiration_date date,
    created_at timestamptz,
    updated_at timestamptz
)
sales(
    id uuid,
    product_id uuid references products(id),
    quantity integer,
    sold_at timestamptz
)"""

TRANSLATE_PROMPT_TEMPLATE = """\
You translate a spoken inventory question into a single read-only PostgreSQL
SELECT statement, given this exact schema:

{schema}

Rules:
- Output ONLY the SQL statement. No markdown code fences, no commentary, no
  explanation, no trailing semicolon.
- The statement must be a single SELECT (or WITH ... SELECT) statement.
- Never write INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, GRANT, REVOKE,
  or CREATE.
- Never write more than one statement.

Question: {question}
SQL:"""

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)

_FORBIDDEN_KEYWORDS_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create)\b",
    re.IGNORECASE,
)
_ALLOWED_START_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class Nl2SqlError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def translate_to_sql(question: str) -> str:
    """One-shot Gemini call, isolated from the realtime session's transcript."""
    prompt = TRANSLATE_PROMPT_TEMPLATE.format(schema=SCHEMA_DESCRIPTION, question=question)
    response = _client().models.generate_content(model="gemini-2.5-flash", contents=[prompt])
    text = (response.text or "").strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    text = text.rstrip(";").strip()
    if not text:
        raise Nl2SqlError("the model returned an empty query")
    return text


def is_safe_select(sql: str) -> bool:
    """Text-level guard: single read-only SELECT/WITH statement, no writes/DDL.

    This is a first line of defense, not the only one — the real safety net
    is the readonly_query_role grant restriction enforced in schema.sql.
    """
    stripped = sql.strip()
    if not stripped:
        return False
    if ";" in stripped.rstrip(";"):
        return False  # semicolon before the end => stacked statements
    if not _ALLOWED_START_RE.match(stripped):
        return False
    if _FORBIDDEN_KEYWORDS_RE.search(stripped):
        return False
    return True

"""Hardened read-only query tool for EMAPI source-DB analysis.

Runs ON the atlas EC2 box (source DBs are IP-restricted), inside the
ygg-atlas backend image. SQL comes on stdin.

Safety layers (defense in depth — production Aurora reader):
  1. single statement, must start with SELECT / WITH / EXPLAIN (no ANALYZE)
  2. write/DDL/admin keywords rejected outright
  3. executed inside a READ ONLY transaction, always rolled back
  4. statement_timeout 20s, lock_timeout 2s
  5. output capped (rows, cell width) and PII-redacted (emails, phones, long digit runs)

Usage: q.py <database> [max_rows]   (SQL on stdin)
       q.py --list                  (list databases visible to the role)
"""

import asyncio
import json
import re
import sys
from decimal import Decimal

import asyncpg
from dotenv import dotenv_values

ENV_FILE = "/work/src.env"
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|analyze|cluster|reindex|refresh|call|do|lock|listen|notify|set\s+role|"
    r"pg_terminate_backend|pg_cancel_backend|pg_sleep|dblink|lo_import|lo_export|"
    r"pg_read_file|pg_ls_dir)\b",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
MAX_CELL = 160


def fail(msg: str) -> None:
    print(json.dumps({"error": msg}))
    sys.exit(1)


def check_sql(sql: str) -> str:
    body = sql.strip().rstrip(";").strip()
    if not body:
        fail("empty SQL")
    # strip comments before inspection
    scrubbed = re.sub(r"--[^\n]*|/\*.*?\*/", " ", body, flags=re.S)
    if ";" in scrubbed:
        fail("multiple statements are not allowed")
    first = scrubbed.split(None, 1)[0].upper()
    if first not in {"SELECT", "WITH", "EXPLAIN"}:
        fail("only SELECT / WITH / EXPLAIN are allowed")
    # string literals may legitimately contain keywords; inspect code outside quotes
    code_only = re.sub(r"'(?:[^']|'')*'", "''", scrubbed)
    hit = FORBIDDEN.search(code_only)
    if hit:
        fail(f"forbidden keyword: {hit.group(0)}")
    return body


def redact(value):
    if value is None:
        return None
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    text = str(value)
    text = EMAIL.sub("<email>", text)
    text = PHONE.sub("<phone>", text)
    if len(text) > MAX_CELL:
        text = text[:MAX_CELL] + "…"
    return text


def conn_kwargs(database: str) -> dict:
    env = dotenv_values(ENV_FILE)
    host = (env.get("EMAPI_SHARED_DB_URL") or "").strip().strip("'\"")
    host = re.sub(r"^[a-z0-9+]+://", "", host).split("/")[0]
    port = 5432
    if ":" in host:
        host, port_s = host.rsplit(":", 1)
        port = int(port_s)
    user = (env.get("EMAPI_SHARED_DB_USERNAME") or "").strip().strip("'\"")
    password = (env.get("EMAPI_SHARED_DB_PASWWORD") or env.get("EMAPI_SHARED_DB_PASSWORD") or "")
    password = password.strip().strip("'\"")
    if not (host and user and password):
        fail("EMAPI_SHARED_DB_* env vars missing")
    return {"host": host, "port": port, "user": user, "password": password,
            "database": database, "ssl": "prefer", "timeout": 15}


async def run(database: str, sql: str, max_rows: int) -> None:
    conn = await asyncpg.connect(**conn_kwargs(database))
    try:
        tr = conn.transaction(readonly=True)
        await tr.start()
        try:
            await conn.execute("SET LOCAL statement_timeout = '20s'")
            await conn.execute("SET LOCAL lock_timeout = '2s'")
            stmt = await conn.prepare(sql)
            cols = [a.name for a in stmt.get_attributes()]
            # server-side cursor: never pull more than the cap over the wire
            cursor = await stmt.cursor()
            rows = await cursor.fetch(max_rows + 1)
        finally:
            await tr.rollback()
    finally:
        await conn.close()
    truncated = len(rows) > max_rows
    out = [[redact(v) for v in r.values()] for r in rows[:max_rows]]
    print(json.dumps({"columns": cols, "rows": out, "row_count": len(out),
                      "truncated": truncated}, default=str))


async def list_dbs() -> None:
    conn = await asyncpg.connect(**conn_kwargs("postgres"))
    try:
        rows = await conn.fetch(
            "SELECT datname FROM pg_database WHERE NOT datistemplate "
            "AND has_database_privilege(datname, 'CONNECT') ORDER BY 1"
        )
        ro = await conn.fetchval("SELECT pg_is_in_recovery()")
        print(json.dumps({"databases": [r["datname"] for r in rows], "is_replica": ro}))
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        asyncio.run(list_dbs())
        return
    if len(sys.argv) < 2:
        fail("usage: q.py <database> [max_rows] < query.sql")
    database = sys.argv[1]
    if not re.fullmatch(r"[a-z0-9_]+", database):
        fail("invalid database name")
    max_rows = min(int(sys.argv[2]) if len(sys.argv) > 2 else 200, 500)
    sql = check_sql(sys.stdin.read())
    try:
        asyncio.run(run(database, sql, max_rows))
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        fail(f"{type(exc).__name__}: {exc}")
    except (OSError, asyncio.TimeoutError) as exc:
        fail(f"connection: {exc}")


if __name__ == "__main__":
    main()

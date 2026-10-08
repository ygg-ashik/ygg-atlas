import os
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlmodel import SQLModel

import app.access.models  # registers the access tables for create_all
import app.identity.models  # noqa: F401  # registers the users table for create_all
from app.atlas.registry import reset_registry
from app.config import get_settings
from app.database import get_engine, get_session_factory
from app.sources import reset_plugins

# Settings fail closed (unset ENVIRONMENT means production), and some test modules
# import app.main, which reads settings, at collection time, before any fixture runs.
os.environ["ENVIRONMENT"] = "test"


@pytest.fixture(scope="session", autouse=True)
def _test_env(tmp_path_factory):
    dbfile = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{dbfile}"
    os.environ["APPDB_URL"] = f"sqlite+aiosqlite:///{dbfile}"
    os.environ["AUTH_DISABLED"] = "true"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ["CHAT_DAILY_MESSAGE_LIMIT"] = "5"

    get_settings.cache_clear()


DEMO_DDL = [
    """CREATE TABLE IF NOT EXISTS demo_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, channel TEXT,
        amount NUMERIC, status TEXT, created_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS demo_customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, segment TEXT, created_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS demo_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event TEXT,
        created_at TIMESTAMP)""",
]

FUNNEL_COUNTS = [
    ("view_product", 100),
    ("add_to_cart", 60),
    ("begin_checkout", 40),
    ("payment_info", 25),
    ("purchase", 20),
]


async def seed_demo(conn, days: int = 10) -> None:
    """Deterministic demo rows.

    Per day: 5x100 paid b2c + 2x500 paid b2b + 1x50 refunded.
    """
    for stmt in DEMO_DDL:
        await conn.execute(text(stmt))
    for tbl in ("demo_orders", "demo_customers", "demo_events"):
        await conn.execute(text(f"DELETE FROM {tbl}"))

    today = datetime.now(UTC).date()
    for day_offset in range(1, days + 1):
        noon = datetime.combine(
            today - timedelta(days=day_offset), time(12), tzinfo=UTC
        )
        orders = (
            [("b2c", 100, "paid")] * 5
            + [("b2b", 500, "paid")] * 2
            + [("b2c", 50, "refunded")]
        )
        for i, (channel, amount, status) in enumerate(orders):
            await conn.execute(
                text(
                    "INSERT INTO demo_orders"
                    " (customer_id, channel, amount, status, created_at)"
                    " VALUES (:c, :ch, :a, :s, :t)"
                ),
                {
                    "c": day_offset * 10 + i,
                    "ch": channel,
                    "a": amount,
                    "s": status,
                    "t": noon,
                },
            )
        for segment in ("consumer", "consumer", "corporate"):
            await conn.execute(
                text(
                    "INSERT INTO demo_customers (segment, created_at) VALUES (:s, :t)"
                ),
                {"s": segment, "t": noon},
            )
        for event, count in FUNNEL_COUNTS:
            for user in range(count):
                await conn.execute(
                    text(
                        "INSERT INTO demo_events (user_id, event, created_at)"
                        " VALUES (:u, :e, :t)"
                    ),
                    {"u": day_offset * 1000 + user, "e": event, "t": noon},
                )


@pytest_asyncio.fixture
async def db():
    """Fresh app schema + seeded demo data on the shared test database."""
    reset_plugins()
    reset_registry()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
        await seed_demo(conn)
        await conn.execute(
            text(
                "INSERT INTO policy_state (id, policy_version, updated_at) "
                "VALUES (1, 1, :now)"
            ),
            {"now": datetime.now(UTC)},
        )

    async with get_session_factory()() as session:
        yield session

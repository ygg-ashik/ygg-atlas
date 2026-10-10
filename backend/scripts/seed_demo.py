"""Seed deterministic demo data so the atlas answers real questions before
production sources are connected. Idempotent: drops and recreates demo tables.

Per full day, going back 90 days from today (UTC):
  - 5 paid b2c orders of 100 AED + 2 paid b2b orders of 500 AED + 1 refunded 50 AED
    => daily paid revenue = 1500 AED (500 b2c + 1000 b2b), 7 paid orders
  - sales reps: b2b orders are "Lina Saab"; b2c orders alternate "Aisha Khan"
    (even positions in the day's list) and "Omar Haddad" (odd)
    => daily paid orders per rep: Aisha 3, Omar 2, Lina 2
  - 3 new customers (2 consumer, 1 corporate)
  - checkout events: 100 view_product, 60 add_to_cart, 40 begin_checkout,
    25 payment_info, 20 purchase (distinct users per step)

Run: uv run python scripts/seed_demo.py
"""

import asyncio
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.sources.demo.manifest import DemoSettings

DDL = [
    "DROP TABLE IF EXISTS demo_orders",
    "DROP TABLE IF EXISTS demo_customers",
    "DROP TABLE IF EXISTS demo_events",
    """
    CREATE TABLE demo_orders (
        id SERIAL PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        channel TEXT NOT NULL,
        amount NUMERIC NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        sales_rep TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE demo_customers (
        id SERIAL PRIMARY KEY,
        segment TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE demo_events (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
]

FUNNEL_COUNTS = [
    ("view_product", 100),
    ("add_to_cart", 60),
    ("begin_checkout", 40),
    ("payment_info", 25),
    ("purchase", 20),
]


def sales_rep(position: int, channel: str) -> str:
    """Deterministic rep for the order at `position` in a day's order list."""
    if channel == "b2b":
        return "Lina Saab"
    return "Aisha Khan" if position % 2 == 0 else "Omar Haddad"


async def seed() -> None:
    engine = create_async_engine(DemoSettings().appdb_url)
    today = datetime.now(UTC).date()

    async with engine.begin() as conn:
        for stmt in DDL:
            await conn.execute(text(stmt))

        for day_offset in range(1, 91):
            day = today - timedelta(days=day_offset)
            noon = datetime.combine(day, time(12, 0), tzinfo=UTC)

            orders = (
                [("b2c", 100, "paid")] * 5
                + [("b2b", 500, "paid")] * 2
                + [("b2c", 50, "refunded")]
            )
            for i, (channel, amount, status) in enumerate(orders):
                await conn.execute(
                    text(
                        "INSERT INTO demo_orders"
                        " (customer_id, channel, amount, status, created_at,"
                        " sales_rep)"
                        " VALUES (:c, :ch, :a, :s, :t, :r)"
                    ),
                    {
                        "c": day_offset * 10 + i,
                        "ch": channel,
                        "a": amount,
                        "s": status,
                        "t": noon,
                        "r": sales_rep(i, channel),
                    },
                )

            for segment in ("consumer", "consumer", "corporate"):
                await conn.execute(
                    text(
                        "INSERT INTO demo_customers (segment, created_at)"
                        " VALUES (:s, :t)"
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

    await engine.dispose()
    print(f"Seeded 90 days of demo data up to {today - timedelta(days=1)} (UTC)")


if __name__ == "__main__":
    asyncio.run(seed())

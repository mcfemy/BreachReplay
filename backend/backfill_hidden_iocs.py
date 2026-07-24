"""
Backfill hidden_iocs onto the 5 flagship scenarios that were seeded before the
hidden_iocs column/data existed. Matches by source_reference and updates only
the hidden_iocs column — no other fields, no other tables.

Reuses seed.py's SCENARIOS list (not a copy) so the backfilled data can never
drift from what a fresh seed would produce.

Run from the backend directory:
    python backfill_hidden_iocs.py
"""
import asyncio
import os

os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", "postgresql+asyncpg://breach_user:breach_pass@localhost:5432/breachreplay"))

from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.scenario import Scenario
from seed import SCENARIOS

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def backfill():
    async with SessionLocal() as session:
        updated = 0
        for data in SCENARIOS:
            ref = data.get("source_reference")
            hidden_iocs = data.get("hidden_iocs")
            if not hidden_iocs:
                print(f"  skip (no hidden_iocs in seed.py): {data['title']}")
                continue
            result = await session.execute(
                update(Scenario)
                .where(Scenario.source_reference == ref)
                .values(hidden_iocs=hidden_iocs)
            )
            if result.rowcount:
                print(f"  updated: {data['title']} ({result.rowcount} row, {len(hidden_iocs)} IOCs)")
                updated += result.rowcount
            else:
                print(f"  no match: {data['title']} (source_reference={ref} not found in DB)")
        await session.commit()
        print(f"Backfilled hidden_iocs on {updated} scenario row(s).")


if __name__ == "__main__":
    asyncio.run(backfill())

import os
import sys
import uuid

# ── Test database safety guard (docs/TEST_DATABASE_SAFETY_SPEC.md) ──────────
# Runs BEFORE the setdefault calls below — the whole point is checking
# whatever was ALREADY set in the environment (e.g. docker-compose's
# env_file injecting the real DATABASE_URL inside a deployed container,
# before Python even starts) before this file's own sqlite default would
# apply. Two production incidents in one evening (2026-07-24/25) came from
# exactly this: running pytest manually inside a deployed container
# inherits the real DATABASE_URL, and 9 test files (not just one) write
# real, non-rolled-back rows via AsyncSessionLocal directly whenever it
# resolves to something real. CI is unaffected (.github/workflows/ci.yml
# sets no DATABASE_URL at all — always hits the sqlite default below).
_PROD_DATABASE_NAMES = {"breachreplay"}  # exact, hardcoded — never derived
# from config that could itself be wrong the same way DATABASE_URL was
# wrong tonight. A defense-in-depth backstop, checked in ADDITION to the
# naming-convention check below, not instead of it.
_TEST_DATABASE_SUFFIX = "_test"


def _unsafe_database_url_reason(url: str) -> str | None:
    """Pure classifier, no I/O/exit — returns None if `url` is safe for
    tests to point at (empty/unset, sqlite, or a Postgres database name
    ending in `_TEST_DATABASE_SUFFIX`), else a human-readable reason it was
    refused. Split out from the exit-on-failure wrapper below specifically
    so it's directly unit-testable (see test_conftest_database_guard.py)
    without subprocess gymnastics around conftest.py's own import-time
    side effects."""
    if not url or "sqlite" in url:
        return None
    dbname = url.split("?", 1)[0].rsplit("/", 1)[-1]
    if dbname in _PROD_DATABASE_NAMES:
        return f"resolves to {dbname!r}, the real production database name"
    if not dbname.endswith(_TEST_DATABASE_SUFFIX):
        return (
            f"resolves to database {dbname!r}, which doesn't look like an "
            f"isolated test database (expected a name ending in "
            f"{_TEST_DATABASE_SUFFIX!r}, sqlite, or unset)"
        )
    return None


def _refuse_unsafe_database_urls() -> None:
    for var in ("DATABASE_URL", "SYNC_DATABASE_URL"):
        reason = _unsafe_database_url_reason(os.environ.get(var, ""))
        if reason is not None:
            sys.stderr.write(
                f"\nREFUSING TO RUN TESTS: {var} {reason}.\n"
                f"Tests write real, non-rolled-back rows via AsyncSessionLocal "
                f"directly in 9 files (action_run_store.finalize and 8 test "
                f"files that bypass the rolled-back db fixture on purpose) — "
                f"running against this database would corrupt real data. See "
                f"docs/TEST_DATABASE_SAFETY_SPEC.md.\n"
                f"Unset {var} to use the sqlite default, or point it at an "
                f"isolated database whose name ends in "
                f"{_TEST_DATABASE_SUFFIX!r}.\n\n"
            )
            sys.exit(1)


_refuse_unsafe_database_urls()

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("SYNC_DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["DEBUG"] = "true"

import fakeredis.aioredis as fakeredis_async
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.main import app
from app.models.organization import Organization
from app.models.scenario import Scenario
from app.models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

DECISION_TREE = [
    {
        "id": "gate-001",
        "trigger_timestamp": "+15m",
        "context_summary": "Suspicious lateral movement detected.",
        "options": [
            {"text": "Isolate host", "consequence_if_chosen": "Containment initiated"},
            {"text": "Ignore alert", "consequence_if_chosen": "Attacker spreads"},
            {"text": "Collect more logs", "consequence_if_chosen": "Delay increases risk"},
        ],
        "correct_index": 0,
        "consequence_if_wrong": "Attacker maintains persistence.",
        "consequence_if_correct": "Good call.",
        "rationale": "NIST RS.CO-1 requires immediate containment.",
        "nist_control_ref": "RS.CO-1",
        "mitre_technique": "T1021",
    }
]


@pytest.fixture(scope="session", autouse=True)
def disable_rate_limiting():
    """Disable slowapi rate limiter globally during test execution."""
    from app.core.security import limiter
    limiter.enabled = False


@pytest.fixture(scope="session", autouse=True)
def mock_celery_tasks():
    """Globally mock Celery task enqueuing (.delay) to prevent attempts to connect to Redis broker."""
    from unittest.mock import MagicMock
    from app.pipeline.tasks import (
        generate_session_debrief,
        process_uploaded_document_task,
        ingest_cisa_advisories,
        process_advisory_url
    )
    generate_session_debrief.delay = MagicMock(return_value=MagicMock(id="mock-debrief-id"))
    process_uploaded_document_task.delay = MagicMock(return_value=MagicMock(id="mock-ingestion-id"))
    ingest_cisa_advisories.delay = MagicMock(return_value=MagicMock(id="mock-cisa-id"))
    process_advisory_url.delay = MagicMock(return_value=MagicMock(id="mock-url-id"))


@pytest.fixture(autouse=True)
async def setup_redis():
    """Inject a shared FakeRedis instance so no real Redis is needed in tests."""
    import app.core.redis as redis_module

    fake_redis = fakeredis_async.FakeRedis(decode_responses=True)
    redis_module._pool = fake_redis
    yield
    await fake_redis.aclose()
    redis_module._pool = None


@pytest.fixture(autouse=True)
async def dispose_app_engine_pool_after_test():
    """Pre-existing test-infra gap, unrelated to any feature under test:
    several arena tests (test_arena_ai_attacker.py, test_arena_ai_defender.py)
    talk to the real DB via `app.db.session.AsyncSessionLocal` /
    `app.db.session.engine` directly (see ensure_test_user_row's docstring
    above for why), rather than this file's own separate SQLite
    `engine`/`db` fixture (line ~23-25 above, always sqlite+aiosqlite,
    unconditionally).

    `app.db.session.engine`, by contrast, is built from `Settings.DATABASE_URL`,
    which is only sqlite in environments where nothing already exported a
    real `DATABASE_URL` before this file's `os.environ.setdefault(...)` call
    above runs (true in CI, which has no `backend/.env` and no DB service).
    When this suite is run locally via `docker compose run backend pytest`,
    `docker-compose.yml`'s `env_file: ./backend/.env` has already set a real
    Postgres `DATABASE_URL` in the process environment before Python even
    starts, so the `setdefault` above is a no-op and `app.db.session.engine`
    is a real asyncpg pool (`pool_pre_ping=True`) — a Postgres FK violation
    from Phase J's test fixes (see ensure_test_user_row) was reproduced and
    confirmed exactly this way. Under that pool, a connection checked out by
    one test can outlive its event loop (pytest-asyncio creates a new loop
    per test function), and the next test to reuse it triggers
    pool_pre_ping's keep-alive probe against the dead loop, raising
    `RuntimeError: ... got Future ... attached to a different loop`. Disposing
    the pool after every test forces a fresh connection under the current
    loop instead. Under CI's sqlite/NullPool engine this dispose() is a
    harmless no-op (no pool to dispose) — safe in both environments, only
    load-bearing in the Postgres one."""
    yield
    from app.db.session import engine as _real_app_engine
    await _real_app_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


async def ensure_test_user_row(user_id: str, email: str | None = None) -> None:
    """Idempotently ensure a `User` row with the given literal id exists in
    the DB that `app.db.session.AsyncSessionLocal` is bound to.

    Several arena tests (test_arena_ai_attacker.py, test_arena_ai_defender.py)
    exercise the real persistence path via `AsyncSessionLocal` directly
    (rather than the `db`/`test_org` fixtures above, which run against a
    fully separate, always-rolled-back SQLite connection — see
    test_bot_loop_drives_match_to_completion_via_execute_arena_action's
    docstring for why) and create an ArenaMatch row referencing a literal
    placeholder id like "attacker-1"/"defender-1" for attacker_user_id /
    defender_user_id. Those columns are real `ForeignKey("users.id")`
    columns with no DEFERRABLE clause, so Postgres enforces the constraint
    immediately on INSERT — a literal placeholder id with no backing `users`
    row raises ForeignKeyViolationError. This helper creates that backing
    row (once; safe to call repeatedly / from multiple tests) so those
    tests' literal ids are valid.
    """
    from app.db.session import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if existing is not None:
            return
        db.add(
            User(
                id=user_id,
                email=email or f"{user_id}@test.breachreplay.invalid",
                hashed_password=hash_password("StrongPass1!"),
                full_name=user_id,
                role="analyst",
                organization_id=None,
            )
        )
        await db.commit()


@pytest.fixture
async def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def test_org(db):
    org = Organization(name="Test Org", slug=f"test-org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


@pytest.fixture
async def test_user(db, test_org):
    user = User(
        email="analyst@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Test Analyst",
        role="analyst",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": user, "org": test_org}


@pytest.fixture
async def admin_user(db, test_org):
    user = User(
        email="admin@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Test Admin",
        role="admin",
        organization_id=test_org.id,
    )
    db.add(user)
    await db.flush()
    token = create_access_token({"sub": user.id})
    return {"token": token, "user": user, "org": test_org}


@pytest.fixture
async def approved_scenario(db):
    scenario = Scenario(
        title="Colonial Pipeline Replay",
        source_type="manual",
        source_reference="TEST-001",
        difficulty="practitioner",
        status="approved",
        decision_tree=DECISION_TREE,
        # Pinned to 1.0 (no compression): DECISION_TREE's "+15m" gate is
        # deliberately past what any test using this fixture spends in
        # clock-seconds, so it never fires mid-test. Scenario.compression_ratio
        # defaults to 8.0 at the DB level, which would compress +15m to ~112s
        # and fire it well inside these tests' normal action budget — action_
        # engine.py's own compression scaling is covered by its dedicated
        # tests in test_action_engine.py, not here.
        compression_ratio=1.0,
        alert_sequence=[
            {
                "timestamp": "+0m",
                "severity": "high",
                "source_system": "SIEM",
                "rule_id": "RULE-001",
                "description": "Unusual VPN login",
                "raw_log": "src=10.0.0.5 user=svc_backup",
            }
        ],
    )
    db.add(scenario)
    await db.flush()
    return scenario

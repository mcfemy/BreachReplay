import os
import uuid

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

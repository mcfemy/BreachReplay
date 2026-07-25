"""
Tests for the test-database safety guard in conftest.py
(docs/TEST_DATABASE_SAFETY_SPEC.md). Two incidents in one evening
(2026-07-24/25) came from tests writing real, non-rolled-back rows via
AsyncSessionLocal whenever DATABASE_URL already resolved to something real
before conftest.py's own sqlite default applied.

Two layers of test here on purpose: fast, direct unit tests against the
pure classifier (`_unsafe_database_url_reason`) for the actual decision
logic, plus one slower subprocess-based smoke test confirming the whole
wiring in conftest.py (the exit-on-failure wrapper, run at import time)
genuinely refuses to even collect tests against an unsafe URL — the unit
tests alone can't catch a bug in how the classifier's result is *used*.
"""
import os
import subprocess
import sys

from tests.conftest import _unsafe_database_url_reason

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Direct unit tests against the pure classifier ─────────────────────────

def test_empty_or_unset_url_is_safe():
    assert _unsafe_database_url_reason("") is None
    assert _unsafe_database_url_reason(None or "") is None


def test_sqlite_urls_are_always_safe():
    assert _unsafe_database_url_reason("sqlite+aiosqlite:///./test.db") is None
    assert _unsafe_database_url_reason("sqlite:///./test.db") is None


def test_exact_production_database_name_is_refused_even_with_test_looking_host():
    """The hardcoded exact-match denylist is a backstop specifically so a
    misleading hostname (e.g. one that happens to say "test" in it) can't
    accidentally defeat the check — only the database NAME matters here."""
    url = "postgresql+asyncpg://user:pass@test-host.internal:5432/breachreplay"
    reason = _unsafe_database_url_reason(url)
    assert reason is not None
    assert "breachreplay" in reason


def test_database_name_without_test_suffix_is_refused():
    url = "postgresql+asyncpg://user:pass@localhost:5432/some_other_db"
    reason = _unsafe_database_url_reason(url)
    assert reason is not None
    assert "some_other_db" in reason


def test_database_name_with_test_suffix_is_allowed():
    url = "postgresql+asyncpg://user:pass@localhost:5432/breachreplay_test"
    assert _unsafe_database_url_reason(url) is None


def test_query_params_do_not_defeat_the_dbname_extraction():
    """A URL with connection params after the dbname (?sslmode=require etc.)
    must not let the dbname parsing accidentally include them."""
    url = "postgresql+asyncpg://user:pass@localhost:5432/breachreplay?sslmode=require"
    reason = _unsafe_database_url_reason(url)
    assert reason is not None
    assert "breachreplay" in reason
    assert "sslmode" not in reason


# ── Subprocess smoke test: the whole conftest.py wiring, not just the classifier ──

def test_conftest_refuses_to_even_collect_against_the_real_prod_database_name():
    env = dict(os.environ)
    env["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/breachreplay"
    env.pop("SYNC_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_conftest_database_guard.py"],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, f"expected nonzero exit, got 0. stdout={result.stdout!r}"
    assert "REFUSING TO RUN TESTS" in result.stderr
    assert "breachreplay" in result.stderr


def test_conftest_collects_normally_with_no_database_url_set():
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env.pop("SYNC_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_conftest_database_guard.py"],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"expected clean collection. stderr={result.stderr!r}"
    assert "REFUSING TO RUN TESTS" not in result.stderr

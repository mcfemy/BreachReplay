"""Tiny in-process TTL cache for public, unauthenticated aggregate-stats
endpoints (Live Breach Events Phase 3 — "Global Incident Response Index").

Caching mechanism choice: an in-process `{key: (computed_at_monotonic, value)}`
dict, NOT `app.core.redis.get_redis()`'s async Redis pool (already used
elsewhere in this app for rate limiting / matchmaking state).

Reasoning:
  - The parent plan's own wording calls this cache "in-process" — cross-
    process/cross-instance consistency was never a requirement here.
  - This app currently runs as a single backend process (see
    `docker-compose.yml` / EC2 deployment notes) — there's no fleet of
    workers that would see divergent cached values long enough to matter.
    Even if that changes later, every process converges to the same value
    within one TTL window on its own, and a public stats page being stale
    by a few minutes across two instances is a total non-issue (it's
    marketing copy, not a security or billing-sensitive value).
  - Avoiding a Redis round-trip (network hop + (de)serialization) on every
    cache-hit for what is expected to be the most-hit public endpoint in
    this initiative is a small but real win, and skips having to reason
    about JSON-encoding datetimes/None through Redis.
  - `cachetools`/`TTLCache` isn't a dependency anywhere in this codebase
    (checked) and pulling it in for ~15 lines of logic isn't worth a new
    dependency.

Uses `time.monotonic()` (never wall-clock `time.time()`/`datetime.utcnow()`)
so the TTL can't be fooled by a system clock adjustment (NTP step, manual
change, DST-adjacent bugs, etc).
"""
import time
from typing import Any, Optional


class TTLCache:
    """A minimal per-key TTL cache. Not thread-safe in the general sense,
    but this app's single-process async event loop never preempts a plain
    dict read/write mid-operation, so no lock is needed here."""

    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        computed_at_monotonic, value = entry
        if time.monotonic() - computed_at_monotonic > self.ttl_seconds:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        """Test-only escape hatch — module-level cache instances otherwise
        persist across the whole pytest session since they're created once
        at import time."""
        self._store.clear()

"""Public Action Console run replay — share-token mint + redacted DTO.

Mirrors Arena's Phase 1 share-link contract (app.api.routes.arena:
POST /arena/matches/{id}/share → share_token → GET /arena/public/replay/{token})
without inventing a second convention: opaque token, never a raw run_id in
the URL; public GET is unauthenticated and 404s for missing / non-shareable
tokens without distinguishing them.

The DTO is a locked key set. Anything not in PUBLIC_DTO_KEYS is a leak —
the public page is fully unauthenticated, so this is the same class of
boundary as the dossier lock (incident_narrative withheld server-side)
and fog-of-war unknown-tier hosts (_UNKNOWN_HOST_FIELDS). The GET route
must never compile/replay a seed; it only re-locks keys already frozen
onto ActionRun.public_snapshot at finalize.
"""
from typing import Any, Optional

from app.models.user import User
from app.services import verb_engine
from app.services.technique_dossier import TECHNIQUE_DOSSIER

# daily/scenario only. Teaser runs have no authenticated owner and must
# never become a public, unauthenticated page.
SHAREABLE_MODES = frozenset({"daily", "scenario"})

# Frontend path — deliberately /r/{token}, not Arena's /replay/{token}.
SHARE_URL_PREFIX = "/r"

# Public-facing label when the owner hasn't opted into arena_profile_public.
# Same contract as arena._public_participant_label's "Player A"/"Player B"
# placeholders: stable, never user_id / email / full_name.
PUBLIC_PLAYER_PLACEHOLDER = "Responder"

PUBLIC_DTO_KEYS = frozenset({
    "outcome",
    "score",
    "score_pct",
    "duration_seconds",
    "scenario_title",
    "mode",
    "player_label",
    "timeline",
    "hosts",
    "edges",
    "techniques_encountered",
})

PUBLIC_TIMELINE_KEYS = frozenset({
    "sequence_number", "verb", "elapsed_seconds", "cost",
})

# Known-tier host: verb_engine._host_summary plus the snapshot's x/y.
# No visibility marker (that's unknown-tier only), no forensics.
PUBLIC_KNOWN_HOST_KEYS = frozenset({
    "id", "hostname", "role", "network_segment_id",
    "compromise_level", "isolated", "x", "y",
})

PUBLIC_UNKNOWN_HOST_KEYS = verb_engine._UNKNOWN_HOST_FIELDS

PUBLIC_TECHNIQUE_KEYS = frozenset({"technique_id", "name", "description"})

PUBLIC_EDGE_KEYS = frozenset({"source", "target"})


def public_player_label(user: Optional[User]) -> str:
    """Same opt-in handle contract as arena._public_participant_label —
    arena_profile_public + public_display_handle, else the stable
    placeholder. Never email, full_name, or user_id."""
    if user and user.arena_profile_public and user.public_display_handle:
        return user.public_display_handle
    return PUBLIC_PLAYER_PLACEHOLDER


def _pick(row: dict, keys: frozenset[str]) -> dict:
    return {k: row[k] for k in keys if k in row}


def _redact_host(host: Any) -> Optional[dict]:
    if not isinstance(host, dict) or "id" not in host:
        return None
    if host.get("visibility") == "unknown":
        return _pick(host, PUBLIC_UNKNOWN_HOST_KEYS)
    return _pick(host, PUBLIC_KNOWN_HOST_KEYS)


def _redact_timeline_entry(entry: Any) -> Optional[dict]:
    """Verbs the player actually issued, with target/correct/warranted
    stripped. `target` is an IP, username, host id, or party id — none of
    those belong on an unauthenticated page."""
    if not isinstance(entry, dict):
        return None
    redacted = _pick(entry, PUBLIC_TIMELINE_KEYS)
    if "verb" not in redacted:
        return None
    return redacted


def _redact_technique(entry: Any) -> Optional[dict]:
    if not isinstance(entry, dict) or "technique_id" not in entry:
        return None
    return _pick(entry, PUBLIC_TECHNIQUE_KEYS)


def _redact_edge(entry: Any) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    redacted = _pick(entry, PUBLIC_EDGE_KEYS)
    if "source" not in redacted or "target" not in redacted:
        return None
    return redacted


def _techniques_summary(technique_ids: frozenset) -> list[dict]:
    """Same {technique_id, name, description} lock as
    action_run_store._techniques_encountered_summary / run.end — NOT the
    dossier's incident_narrative / source_reference."""
    return [
        {
            "technique_id": technique_id,
            "name": TECHNIQUE_DOSSIER[technique_id]["name"],
            "description": TECHNIQUE_DOSSIER[technique_id]["description"],
        }
        for technique_id in sorted(technique_ids)
        if technique_id in TECHNIQUE_DOSSIER
    ]


def freeze_public_snapshot(run_state) -> dict:
    """Redacted map + techniques, frozen at finalize. Drops
    revealed_iocs / notified_party_ids from earned_state_snapshot — those
    carry raw_log / party identity that the public DTO must not grow."""
    earned = verb_engine.earned_state_snapshot(run_state)
    hosts = [h for h in (_redact_host(h) for h in earned.get("hosts", [])) if h is not None]
    edges = [e for e in (_redact_edge(e) for e in earned.get("edges", [])) if e is not None]
    return {
        "hosts": hosts,
        "edges": edges,
        "techniques_encountered": _techniques_summary(run_state.encountered_technique_ids),
    }


def _score_pct(score_breakdown: Any) -> int:
    """Pull ONLY the integer percentage off score_breakdown. The rest of
    that JSONB (collateral hostnames, notification warranted/rationale)
    must never ride onto the public DTO."""
    if not isinstance(score_breakdown, dict):
        return 0
    raw = score_breakdown.get("score_pct")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def build_public_replay_dto(
    action_run,
    scenario_title: str,
    player_label: str,
) -> Optional[dict]:
    """Locked public view of a completed Action Console run. Returns None
    when the row is not shareable (missing snapshot, teaser mode) so the
    route can 404 without leaking why."""
    if action_run.mode not in SHAREABLE_MODES:
        return None
    snapshot = action_run.public_snapshot
    if not isinstance(snapshot, dict):
        return None

    hosts = [h for h in (_redact_host(h) for h in snapshot.get("hosts", [])) if h is not None]
    edges = [e for e in (_redact_edge(e) for e in snapshot.get("edges", [])) if e is not None]
    techniques = [
        t for t in (_redact_technique(t) for t in snapshot.get("techniques_encountered", []))
        if t is not None
    ]
    timeline = [
        e for e in (_redact_timeline_entry(e) for e in (action_run.action_log or []))
        if e is not None
    ]

    return {
        "outcome": action_run.outcome,
        "score": action_run.total_score,
        "score_pct": _score_pct(action_run.score_breakdown),
        "duration_seconds": action_run.duration_seconds,
        "scenario_title": scenario_title,
        "mode": action_run.mode,
        "player_label": player_label,
        "timeline": timeline,
        "hosts": hosts,
        "edges": edges,
        "techniques_encountered": techniques,
    }

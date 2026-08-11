"""Phase 2.5 CMMC Evidence Layer — designation and aggregation (build-order
item 3).

Two responsibilities, kept together since both operate on the same
ActionRun<->EvidenceSession relationship:
1. Validating and applying designation (attaching completed runs to a
   session) — all-or-nothing over a batch, never a silent partial success
   or a silent re-parent away from another session.
2. Building the per-participant / session-level aggregate view. The
   central design rule, reported and approved before this was written:
   the session-level summary never computes a single "outcome" — see
   build_evidence_session_aggregate's docstring for the full reasoning.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_run import ActionRun
from app.models.evidence_session import EvidenceSession
from app.models.membership import Membership
from app.models.user import User

OUTCOME_STATES = (
    "contained", "contained_at_cost", "overreacted",
    "breached_spread_limited", "breached",
)


async def list_client_org_runs(
    db: AsyncSession, client_org_id: str,
    *, designated: Optional[bool] = None, scenario_id: Optional[str] = None,
) -> list[ActionRun]:
    """Every ActionRun belonging to a client_participant Membership of this
    client org — the pool a consultant_admin picks from to designate.
    `designated=False` (the common case: "what's available to designate")
    filters to evidence_session_id IS NULL; True filters to already-
    designated runs; None (default) returns both."""
    participant_ids_result = await db.execute(
        select(Membership.user_id).where(
            Membership.client_org_id == client_org_id,
            Membership.role == "client_participant",
        )
    )
    participant_ids = [row[0] for row in participant_ids_result.all()]
    if not participant_ids:
        return []

    query = select(ActionRun).where(ActionRun.user_id.in_(participant_ids))
    if designated is True:
        query = query.where(ActionRun.evidence_session_id.is_not(None))
    elif designated is False:
        query = query.where(ActionRun.evidence_session_id.is_(None))
    if scenario_id is not None:
        query = query.where(ActionRun.scenario_id == scenario_id)

    result = await db.execute(query.order_by(ActionRun.created_at.desc()))
    return list(result.scalars().all())


async def validate_run_for_designation(
    db: AsyncSession, session: EvidenceSession, run: ActionRun,
) -> Optional[str]:
    """None if `run` may be attached to `session`, else a human-readable
    reason it can't be. Three independent checks, each closing a real
    integrity/isolation hole:
    - scenario match: an exercise is one scenario: a run for a different
      scenario isn't a data point in this session, it's a different one.
    - client-org membership: blocks attaching a run with no relationship
      to this client org at all — including a consultant's own solo runs,
      which have no client_participant Membership anywhere.
    - not already designated elsewhere: re-submitting a run already in
      *this* session is a no-op (idempotent), but a run already in a
      *different* session must be rejected loudly, not silently
      re-parented out from under another evidence pack."""
    if run.scenario_id != session.scenario_id:
        return "run's scenario does not match this evidence session's scenario"

    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == run.user_id,
            Membership.client_org_id == session.client_org_id,
            Membership.role == "client_participant",
        )
    )
    if membership_result.scalar_one_or_none() is None:
        return "run's user is not a client_participant of this evidence session's client org"

    if run.evidence_session_id is not None and run.evidence_session_id != session.id:
        return "run is already designated into a different evidence session"

    return None


async def designate_runs(
    db: AsyncSession, session: EvidenceSession, run_ids: list[str],
) -> dict[str, str]:
    """Validates every run_id first; if any fails, attaches NOTHING and
    returns {run_id: reason} for every failure (empty dict means every run
    passed and has now been attached — the only case with a side effect).
    All-or-nothing: a consultant designating 5 runs must never end up with
    3 silently attached and 2 silently skipped."""
    errors: dict[str, str] = {}
    valid_runs: list[ActionRun] = []

    for run_id in run_ids:
        run = await db.get(ActionRun, run_id)
        if run is None:
            errors[run_id] = "run not found"
            continue
        reason = await validate_run_for_designation(db, session, run)
        if reason is not None:
            errors[run_id] = reason
            continue
        valid_runs.append(run)

    if errors:
        return errors

    for run in valid_runs:
        run.evidence_session_id = session.id
    await db.flush()
    return {}


async def _participant_names(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: (u.full_name or u.email) for u in result.scalars().all()}


async def runs_with_participant_names(db: AsyncSession, runs: list[ActionRun]) -> list[dict]:
    """Shared by the run-listing and session-view routes: each run plus
    its participant's display name, batched into one User lookup rather
    than one query per run."""
    names = await _participant_names(db, {r.user_id for r in runs if r.user_id})
    return [
        {
            "id": run.id,
            "user_id": run.user_id,
            "participant_name": names.get(run.user_id, "Unknown participant"),
            "scenario_id": run.scenario_id,
            "outcome": run.outcome,
            "total_score": run.total_score,
            "duration_seconds": run.duration_seconds,
            "evidence_session_id": run.evidence_session_id,
            "created_at": run.created_at,
        }
        for run in runs
    ]


async def build_evidence_session_aggregate(db: AsyncSession, session: EvidenceSession) -> dict:
    """The per-participant / session-level view build-order item 6 (PDF
    generation) will eventually render. Central design rule, reported and
    approved before this was written: there is no single session-level
    "outcome" anywhere in this payload — not an average, not a "mostly
    contained" label. A team's exercise produces several independently
    graded outcomes, and averaging or collapsing them would report
    something that didn't happen. Instead:

    - `outcome_distribution` is a full histogram over all 5 named states
      (zero-filled, all keys always present) — the entire "how did the
      exercise go" answer lives in this dict's shape, never a scalar.
    - `participants` keeps every run's score_breakdown fields exactly as
      verb_engine.compute_score produced them, never touched.
    - `collateral_total_penalty` sums what's legitimately additive (real
      cost, in the same units as each participant's own collateral_penalty)
      while every participant's own collateral list stays individually
      visible too — attribution matters for item 5's after-action review.
    - evidence_found/evidence_total are deliberately NOT summed into a
      session total: item 1's plan flagged that discovered IOC identities
      are never persisted, only counts, so two participants each finding
      the same IOC independently would double-count under a naive sum
      with no way to deduplicate. Per-participant counts only.
    - `timeline` merges every participant's action_log into one list,
      each entry tagged with who did it, sorted by an `estimated_timestamp`
      reconstructed from that run's own created_at/duration_seconds/
      elapsed_seconds (see inline comment below for why this is an honest
      reconstruction, not a guess).
    - `escalations` is the same pooling applied to just the escalate verb
      — "notification decisions, pooled": that an escalation happened, who
      triggered it, roughly when, WHICH party it targeted (`target`), and
      (Phase 3 — this was the gap item 1's original plan flagged and left
      unresolved: escalate used to carry no target detail at all) whether
      that party was warranted per the scenario's own authored
      `notification_matrix` (`warranted`). `warranted` is `None` for any
      pre-Phase-3 historical row whose `action_log` entries predate this
      field.
    """
    result = await db.execute(select(ActionRun).where(ActionRun.evidence_session_id == session.id))
    runs = list(result.scalars().all())

    names = await _participant_names(db, {r.user_id for r in runs if r.user_id})

    outcome_distribution = {state: 0 for state in OUTCOME_STATES}
    participants = []
    timeline = []
    collateral_total_penalty = 0

    for run in runs:
        outcome_distribution[run.outcome] = outcome_distribution.get(run.outcome, 0) + 1
        participant_name = names.get(run.user_id, "Unknown participant")
        sb = run.score_breakdown
        collateral_penalty = sb.get("collateral_penalty", 0)
        collateral_total_penalty += collateral_penalty

        participants.append({
            "run_id": run.id,
            "user_id": run.user_id,
            "participant_name": participant_name,
            "outcome": run.outcome,
            "total_score": run.total_score,
            "score_pct": sb.get("score_pct", 0.0),
            "evidence_found": sb.get("evidence_found", 0),
            "evidence_total": sb.get("evidence_total", 0),
            "collateral": sb.get("collateral", []),
            "collateral_penalty": collateral_penalty,
            "duration_seconds": run.duration_seconds,
        })

        # run.duration_seconds IS run_state.elapsed_seconds at the instant
        # finalize() wrote this row (action_run_store.finalize) — the same
        # clock every action_log entry's own elapsed_seconds is relative
        # to. So created_at - duration_seconds is exactly this run's start
        # instant, and adding each entry's elapsed_seconds back on is an
        # honest reconstruction of when it happened, not a guess. It's
        # still only an ESTIMATE for cross-participant ordering, since two
        # participants' runs don't necessarily start at the same real
        # moment — the field name says so.
        run_start = run.created_at - timedelta(seconds=run.duration_seconds)
        for entry in run.action_log:
            timeline.append({
                "participant_user_id": run.user_id,
                "participant_name": participant_name,
                "sequence_number": entry["sequence_number"],
                "verb": entry["verb"],
                "target": entry.get("target"),
                # Phase 3 — present (a real bool) only on "escalate" entries;
                # `None` for every other verb, which don't carry it at all.
                "warranted": entry.get("warranted"),
                "elapsed_seconds_in_run": entry["elapsed_seconds"],
                "estimated_timestamp": run_start + timedelta(seconds=entry["elapsed_seconds"]),
            })

    timeline.sort(key=lambda e: e["estimated_timestamp"])
    escalations = [e for e in timeline if e["verb"] == "escalate"]

    return {
        "evidence_session_id": session.id,
        "participant_count": len(runs),
        "outcome_distribution": outcome_distribution,
        "participants": participants,
        "collateral_total_penalty": collateral_total_penalty,
        "timeline": timeline,
        "escalations": escalations,
    }

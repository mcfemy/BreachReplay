"""ELO-style rating engine for Live Arena Mode (Phase I).

Pure function core (`compute_new_ratings`) plus a thin DB-application
wrapper (`apply_match_result`) called exactly once, at the moment a match
reaches a terminal, decisive status, from
`app.websocket.handlers._mark_match_completed_if_needed`.
"""
from sqlalchemy import select

from app.models.user import User

K_FACTOR = 32

# Fixed "phantom" rating standing in for the AI bot's skill level in
# human-vs-AI matches — there's no real User row for the bot side, so the
# standard two-real-ratings ELO formula needs a stand-in opponent rating.
# Values are spread around the human default (1200) so beating "hard" is
# worth noticeably more than beating "easy", and losing to "easy" costs
# noticeably more than losing to "hard".
AI_PHANTOM_RATING = {"easy": 900, "medium": 1200, "hard": 1600}


def compute_new_ratings(rating_a: int, rating_b: int, a_won: bool, k: int = K_FACTOR) -> tuple[int, int]:
    """Standard ELO update for one decisive (no-draw) match between A and B.
    Returns (new_rating_a, new_rating_b), each rounded to the nearest int."""
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    expected_b = 1 - expected_a
    score_a = 1.0 if a_won else 0.0
    score_b = 1.0 - score_a
    new_a = rating_a + k * (score_a - expected_a)
    new_b = rating_b + k * (score_b - expected_b)
    return round(new_a), round(new_b)


async def apply_match_result(db, match) -> dict:
    """Update arena_rating/arena_wins/arena_losses/arena_matches_played for
    whichever side(s) of `match` are real users (an AI opponent has no User
    row to update), given `match.status` is already a terminal, decisive
    outcome ("attacker_won" | "defender_won"). Caller MUST have already set
    `match.status`/`completed_at` on the same `db` session — this function
    only stages User row changes, it does NOT commit (the caller's existing
    transaction commits everything together).

    Returns a dict keyed by role ("attacker"/"defender" — only the side(s)
    with a real User row are present), e.g.
    `{"attacker": {"user_id": "u-123", "before": 1200, "after": 1216, "delta": 16}}`
    — keyed by role rather than raw user_id specifically so the WS layer
    (which already routes notifications by role via
    `manager.get_arena_connection(match_id, "attacker"|"defender")`, not by
    user_id) can look up "my side's" change without needing the ArenaMatch
    row in scope.
    """
    if match.status not in ("attacker_won", "defender_won"):
        return {}

    attacker_id = match.attacker_user_id
    defender_id = match.defender_user_id
    attacker_won = match.status == "attacker_won"

    attacker_user = None
    if attacker_id:
        attacker_user = (
            await db.execute(select(User).where(User.id == attacker_id))
        ).scalar_one_or_none()
    defender_user = None
    if defender_id:
        defender_user = (
            await db.execute(select(User).where(User.id == defender_id))
        ).scalar_one_or_none()

    if attacker_user is None and defender_user is None:
        return {}  # neither side is a real user — nothing to rate

    difficulty = getattr(match, "difficulty", None) or "medium"
    phantom = AI_PHANTOM_RATING.get(difficulty, 1200)
    attacker_rating = attacker_user.arena_rating if attacker_user else phantom
    defender_rating = defender_user.arena_rating if defender_user else phantom

    new_attacker_rating, new_defender_rating = compute_new_ratings(
        attacker_rating, defender_rating, attacker_won,
    )

    changes: dict = {}
    if attacker_user is not None:
        before = attacker_user.arena_rating
        attacker_user.arena_rating = new_attacker_rating
        attacker_user.arena_matches_played += 1
        if attacker_won:
            attacker_user.arena_wins += 1
        else:
            attacker_user.arena_losses += 1
        changes["attacker"] = {
            "user_id": attacker_id, "before": before, "after": new_attacker_rating,
            "delta": new_attacker_rating - before,
        }

    if defender_user is not None:
        before = defender_user.arena_rating
        defender_user.arena_rating = new_defender_rating
        defender_user.arena_matches_played += 1
        if not attacker_won:
            defender_user.arena_wins += 1
        else:
            defender_user.arena_losses += 1
        changes["defender"] = {
            "user_id": defender_id, "before": before, "after": new_defender_rating,
            "delta": new_defender_rating - before,
        }

    return changes

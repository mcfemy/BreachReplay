"""Unit tests for ghost_race_beat.is_ghost_race_beat."""

from app.models.action_run import ActionRun
from app.services.ghost_race_beat import is_ghost_race_beat


def test_is_ghost_race_beat_pure_function():
    ghost = ActionRun(
        id="g1",
        user_id="owner",
        scenario_id="s1",
        seed=1,
        mode="scenario",
        action_log=[],
        score_breakdown={},
        total_score=100,
        duration_seconds=120,
        outcome="contained",
    )
    assert is_ghost_race_beat("contained", 90, ghost) is True
    assert is_ghost_race_beat("contained_at_cost", 119, ghost) is True
    assert is_ghost_race_beat("contained", 120, ghost) is False
    assert is_ghost_race_beat("contained", 200, ghost) is False
    assert is_ghost_race_beat("breached", 50, ghost) is False
    assert is_ghost_race_beat("overreacted", 50, ghost) is False

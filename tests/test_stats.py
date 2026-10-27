"""
Tests for the stats engine: small hand-made events where the answer is known,
plus facts from the synthetic match that the agents rely on.
"""

import asyncio

from matchmind import stats
from matchmind.data import load_match
from matchmind.replay import stream

MATCH = load_match("match_002")
INFO, EVENTS = MATCH["match"], MATCH["events"]


def event(id=1, side="home", type="pass", outcome="complete", start=(50, 50), end=(60, 50),
          minute=10, second=0, period=1, under_pressure=False, possession_id=1, **extra):
    team = INFO[side]["name"]
    return {"id": id, "period": period, "minute": minute, "second": second, "team": team, "side": side,
            "player": "Fox" if side == "home" else "Moss", "type": type, "outcome": outcome,
            "start": list(start), "end": list(end) if end else None,
            "possession_id": possession_id, "under_pressure": under_pressure, **extra}


def test_clock_shows_stoppage_time():
    assert stats.clock(event(minute=27, second=40)) == "28'"
    assert stats.clock(event(minute=46, period=1)) == "45+2'"
    assert stats.clock(event(minute=45, period=2)) == "46'"


def test_score_counts_own_goals_for_the_other_team():
    events = [event(type="shot", outcome="goal", xg=0.3), event(side="home", type="own_goal", outcome="goal")]
    assert stats.score(events) == {"home": 1, "away": 1}


def test_pass_difficulty_grows_with_distance_pressure_and_progress():
    short_sideways = event(start=(50, 50), end=(50, 60))
    long_forward_under_pressure = event(start=(40, 50), end=(85, 50), under_pressure=True)
    assert stats.difficulty_label(stats.pass_difficulty(short_sideways)) == "easy"
    assert stats.difficulty_label(stats.pass_difficulty(long_forward_under_pressure)) == "hard"


def test_pass_quality_counts_accuracy_and_progressive_passes():
    events = [event(start=(40, 50), end=(60, 50)), event(outcome="intercepted"), event(type="shot", xg=0.1)]
    quality = stats.pass_quality(events)
    assert (quality["attempted"], quality["completed"], quality["accuracy_pct"]) == (2, 1, 50)
    assert quality["progressive_completed"] == 1


def test_territory_uses_each_teams_own_attacking_direction():
    events = [event(side="home", start=(80, 50)), event(side="home", start=(90, 50)), event(side="away", start=(70, 50))]
    tilt = stats.territory(events, INFO)
    assert tilt["Red Lions"]["field_tilt_pct"] == 67 and tilt["Blue Sharks"]["field_tilt_pct"] == 33


def test_ball_speed_is_only_estimated_when_the_timing_allows():
    shot = event(type="shot", start=(80, 50), end=(100, 50), second=0, xg=0.1)
    save = event(side="away", type="save", outcome="saved", second=1, end=None)
    assert stats.ball_speed_kmh(shot, save) == 76            # 21 m in 1 s
    assert stats.ball_speed_kmh(shot, event(type="throw_in", second=30)) is None


def test_full_match_facts():
    state = stats.match_state(EVENTS, INFO)
    assert state["score"] == {"Red Lions": 3, "Blue Sharks": 2}
    xg = state["expected_goals"]
    assert (xg["Red Lions"]["xg"], xg["Blue Sharks"]["xg"]) == (4.61, 2.48)
    assert xg["Red Lions"]["goals_from_shots"] == 2        # the third was a Blue Sharks own goal


def test_live_state_never_sees_the_future():
    before_first_goal = stats.match_state(stats.events_until(EVENTS, 351), INFO)
    assert before_first_goal["score"] == {"Red Lions": 0, "Blue Sharks": 0}
    assert stats.match_state(stats.events_until(EVENTS, 352), INFO)["score"]["Red Lions"] == 1


def test_player_story_follows_the_captain():
    fox = stats.player_story(EVENTS, INFO, "Fox")
    assert fox["team"] == "Red Lions" and fox["notes"] == {"note": "captain"}
    assert fox["goals"] == 1 and fox["cards"] == ["yellow"]
    texts = [m["text"] for m in fox["moments"]]
    assert "shot (goal, xG 0.26)" in texts and "50th completed pass" in texts


def test_player_story_credits_assists():
    lane = stats.player_story(EVENTS, INFO, "Lane")
    assert lane["assists"] == 1
    assert any(m["text"] == "assist for Fox" for m in lane["moments"])


def test_replay_streams_events_in_order():
    async def first_three():
        return [e["id"] async for e in stream(EVENTS[:3], speed=10_000)]

    assert asyncio.run(first_three()) == [1, 2, 3]


def test_score_matches_the_score_recorded_on_every_goal():
    for goal in (e for e in EVENTS if "score" in e):
        assert stats.score(stats.events_until(EVENTS, goal["id"])) == goal["score"], stats.clock(goal)
    assert stats.score(EVENTS) == INFO["final_score"]


def test_shares_and_counts_stay_consistent_throughout_the_match():
    for i in range(50, len(EVENTS) + 1, 50):
        state = stats.match_state(EVENTS[:i], INFO)
        tilt, possession = zip(*((t["field_tilt_pct"], t["possession_pct"]) for t in state["territory"].values()))
        assert sum(tilt) == 100 and sum(possession) == 100
        assert all(p["completed"] <= p["attempted"] for p in state["passing"].values())
        assert all(x["on_target"] <= x["shots"] for x in state["expected_goals"].values())


def test_pass_distance_and_difficulty_by_hand():
    lane = next(e for e in EVENTS if e["id"] == 351)    # Lane's pass before Fox's goal
    # along 13.9 x 1.05 = 14.6 m, across 6.8 x 0.68 = 4.6 m
    assert round(stats.metres(lane["start"], lane["end"]), 1) == 15.3
    # distance 15.3/50*40 = 12.2, no pressure, 14.6/30*20 = 9.7 forward, not into the box
    assert stats.pass_difficulty(lane) == 22

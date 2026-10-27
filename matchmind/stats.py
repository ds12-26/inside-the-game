"""
Match statistics computed from the event stream. No model involved.

Every function takes the events seen so far (in event order), so the same code
answers "now" during live play and "full time" afterwards. These numbers are
the facts the agents write about and the Fact-Checker verifies against.

Coordinates: x runs 0-100 from the acting team's own goal to the opponent's,
y 0-100 across the pitch. `home_x` turns any event into the home team's view.
"""

import math
from collections import Counter

PITCH_LENGTH_M, PITCH_WIDTH_M = 105, 68
PERIOD_END = {1: 45, 2: 90, 3: 105, 4: 120}   # minute each period is scheduled to end
FINAL_THIRD_X = 100 * 2 / 3
BIG_CHANCE_XG = 0.3
LONG_PASS_M = 40          # passes at least this long are flagged on screen
FAST_SHOT_KMH = 90        # shots at least this fast are flagged on screen
PASS_MILESTONES = (25, 50, 75, 100)


# ---------- basics ----------


def clock(event):
    """Broadcast clock for an event: 28' or 45+2'."""
    minute = event["minute"] + 1
    end = PERIOD_END[event["period"]]
    return f"{end}+{minute - end}'" if minute > end else f"{minute}'"


def seconds(event):
    return event["minute"] * 60 + event["second"]


def events_until(events, at_event=None):
    """Events up to and including event ID `at_event` (all of them if None)."""
    if at_event is None:
        return events
    return [e for e in events if e["id"] <= at_event]


def last_minutes(events, minutes):
    """Events from the last `minutes` of match time before the latest event."""
    if not events or minutes is None:
        return events
    since = seconds(events[-1]) - minutes * 60
    return [e for e in events if seconds(e) >= since]


def home_x(event, x=None):
    """An x coordinate seen from the home team's side of the pitch."""
    x = event["start"][0] if x is None else x
    return x if event["side"] == "home" else 100 - x


def metres(start, end):
    """Distance between two pitch points, in metres."""
    dx = (end[0] - start[0]) * PITCH_LENGTH_M / 100
    dy = (end[1] - start[1]) * PITCH_WIDTH_M / 100
    return math.hypot(dx, dy)


def share(a, b):
    """a as a percentage of a + b, rounded; 50 when both are zero."""
    return round(100 * a / (a + b)) if a + b else 50


def side_of(team, match_info):
    return "home" if match_info["home"]["name"] == team else "away"


# ---------- score ----------


def score(events):
    """Goals per side so far, including own goals for the team credited."""
    goals = {"home": 0, "away": 0}
    for e in events:
        if e["type"] == "shot" and e["outcome"] == "goal":
            goals[e["side"]] += 1
        elif e["type"] == "own_goal":
            goals["away" if e["side"] == "home" else "home"] += 1
    return goals


# ---------- pass quality ----------


def pass_difficulty(event):
    """How hard a pass was, 0-100, from distance, pressure and how far it moves the ball forward."""
    start, end = event["start"], event["end"]
    distance = min(metres(start, end), 50) / 50 * 40
    pressure = 25 if event["under_pressure"] else 0
    forward_m = (end[0] - start[0]) * PITCH_LENGTH_M / 100
    progress = max(0, min(forward_m, 30)) / 30 * 20
    into_box = 15 if end[0] >= 83 else 0
    return round(distance + pressure + progress + into_box)


def difficulty_label(rating):
    return "hard" if rating >= 60 else "medium" if rating >= 35 else "easy"


def is_progressive(event):
    """A pass that moves the ball at least 10 m towards goal and ends in the opponent's half."""
    forward_m = (event["end"][0] - event["start"][0]) * PITCH_LENGTH_M / 100
    return forward_m >= 10 and event["end"][0] > 50


def pass_quality(events, team=None, player=None):
    """Accuracy, distance, difficulty and progression for a team's or player's passes."""
    passes = [e for e in events if e["type"] == "pass"
              and (team is None or e["team"] == team)
              and (player is None or e["player"] == player)]
    complete = [e for e in passes if e["outcome"] == "complete"]
    ratings = [pass_difficulty(e) for e in passes]
    return {
        "attempted": len(passes),
        "completed": len(complete),
        "accuracy_pct": round(100 * len(complete) / len(passes)) if passes else None,
        "avg_distance_m": round(sum(metres(e["start"], e["end"]) for e in passes) / len(passes), 1) if passes else None,
        "avg_difficulty": round(sum(ratings) / len(ratings)) if ratings else None,
        "hard_completed": sum(1 for e in complete if pass_difficulty(e) >= 60),
        "progressive_completed": sum(1 for e in complete if is_progressive(e)),
        "final_third_entries": sum(1 for e in complete if e["start"][0] < FINAL_THIRD_X <= e["end"][0]),
        "under_pressure_accuracy_pct": _accuracy([e for e in passes if e["under_pressure"]]),
    }


def _accuracy(passes):
    if not passes:
        return None
    return round(100 * sum(e["outcome"] == "complete" for e in passes) / len(passes))


# ---------- territory and control ----------


def territory(events, match_info):
    """Who controls the pitch: field tilt, average line, possession and pressure.

    field_tilt_pct: share of all final-third actions made by each team.
    avg_line: average x of each team's actions, from that team's own goal (higher = further up).
    possession_pct: share of passes attempted.
    under_pressure_pct: share of each team's actions made under pressure.
    """
    result = {}
    final_third = Counter(e["side"] for e in events if e["start"][0] >= FINAL_THIRD_X)
    passes = Counter(e["side"] for e in events if e["type"] == "pass")
    for side, other in (("home", "away"), ("away", "home")):
        own = [e for e in events if e["side"] == side]
        result[match_info[side]["name"]] = {
            "field_tilt_pct": share(final_third[side], final_third[other]),
            "avg_line": round(sum(e["start"][0] for e in own) / len(own), 1) if own else None,
            "possession_pct": share(passes[side], passes[other]),
            "under_pressure_pct": round(100 * sum(e["under_pressure"] for e in own) / len(own)) if own else None,
        }
    return result


def control_vs_chaos(events):
    """How settled the game is: long possessions = control, frequent turnovers = chaos."""
    if not events:
        return {"avg_possession_actions": None, "turnovers_per_10_min": None, "state": "unknown"}
    lengths = Counter(e["possession_id"] for e in events)
    avg_length = sum(lengths.values()) / len(lengths)
    turnovers = sum(1 for a, b in zip(events, events[1:]) if a["side"] != b["side"]
                    and b["type"] in ("interception", "tackle"))
    span_min = max(1, (seconds(events[-1]) - seconds(events[0])) / 60)
    per_10 = round(10 * turnovers / span_min, 1)
    state = "chaotic" if per_10 >= 13 else "controlled" if avg_length >= 7.5 or per_10 < 8 else "balanced"
    return {"avg_possession_actions": round(avg_length, 1), "turnovers_per_10_min": per_10, "state": state}


def rhythm(events):
    """Game tempo: actions per minute."""
    if len(events) < 2:
        return {"actions_per_min": None}
    span_min = max(1, (seconds(events[-1]) - seconds(events[0])) / 60)
    return {"actions_per_min": round(len(events) / span_min, 1)}


# ---------- expected goals ----------


def expected_goals(events, match_info):
    """xG, shots and finishing per team, plus the best chances so far."""
    shots = [e for e in events if e["type"] == "shot"]
    goals = score(events)
    teams = {}
    for side in ("home", "away"):
        own = [e for e in shots if e["side"] == side]
        xg = round(sum(e["xg"] for e in own), 2)
        scored = sum(e["outcome"] == "goal" for e in own)
        teams[match_info[side]["name"]] = {
            "xg": xg,
            "goals": goals[side],
            "goals_from_shots": scored,
            "finishing_vs_xg": round(scored - xg, 2),   # below zero = scored fewer than chances deserved
            "shots": len(own),
            "on_target": sum(e["outcome"] in ("goal", "saved") for e in own),
            "big_chances": sum(e["xg"] >= BIG_CHANCE_XG for e in own),
        }
    best = sorted(shots, key=lambda e: e["xg"], reverse=True)[:5]
    return {
        "teams": teams,
        "best_chances": [{"clock": clock(e), "player": e["player"], "team": e["team"],
                          "xg": e["xg"], "outcome": e["outcome"]} for e in best],
    }


# ---------- speed (estimated) ----------


def ball_speed_kmh(event, next_event):
    """Rough ball speed from distance over time to the next event; None if it can't be estimated.

    Event times are whole seconds, so this is an estimate, not a measurement. Only
    used when the ball's next touch follows within 1-2 s (for shots: the save).
    """
    if next_event is None or event["end"] is None:
        return None
    if event["type"] == "shot" and next_event["type"] != "save":
        return None
    dt = seconds(next_event) - seconds(event)
    if not 1 <= dt <= 2:
        return None
    end = [100, 50] if event["type"] == "shot" else event["end"]
    return round(metres(event["start"], end) / dt * 3.6)


# ---------- players ----------


def player_story(events, match_info, player):
    """Everything a player has done so far: totals, pass quality and their moments in order."""
    info = next(p for side in ("home", "away") for p in match_info[side]["players"] if p["name"] == player)
    team = next(match_info[s]["name"] for s in ("home", "away") if info in match_info[s]["players"])
    own = [e for e in events if e["player"] == player]
    counts = Counter((e["type"], e["outcome"]) for e in own)
    shots = [e for e in own if e["type"] == "shot"]
    moments, completed = [], 0
    for i, e in enumerate(events):
        if e["player"] == player:
            if e["type"] == "pass" and e["outcome"] == "complete":
                completed += 1
                if completed in PASS_MILESTONES:
                    moments.append(_moment(e, f"{completed}th completed pass"))
                if metres(e["start"], e["end"]) >= LONG_PASS_M:
                    moments.append(_moment(e, f"long pass, {round(metres(e['start'], e['end']))} m"))
            elif e["type"] == "shot":
                speed = ball_speed_kmh(e, events[i + 1] if i + 1 < len(events) else None)
                text = f"shot ({e['outcome'].replace('_', ' ')}, xG {e['xg']})"
                if speed and speed >= FAST_SHOT_KMH:
                    text += f", about {speed} km/h"
                moments.append(_moment(e, text))
            elif e["type"] in ("save", "card", "own_goal"):
                moments.append(_moment(e, {"save": "save", "card": f"{e['outcome']} card",
                                           "own_goal": "own goal"}[e["type"]]))
        elif e.get("assist") == player:
            moments.append(_moment(e, f"assist for {e['player']}"))
    return {
        "player": player,
        "team": team,
        "position": info["position"],
        "notes": {k: v for k, v in info.items() if k not in ("name", "position")},
        "touches": len(own),
        "passing": pass_quality(events, player=player),
        "shots": len(shots),
        "xg": round(sum(e["xg"] for e in shots), 2),
        "goals": counts[("shot", "goal")],
        "assists": sum(1 for e in events if e.get("assist") == player),
        "tackles_won": counts[("tackle", "won")],
        "interceptions": counts[("interception", "won")],
        "saves": counts[("save", "saved")],
        "fouls_committed": counts[("foul", "committed")],
        "fouls_won": sum(1 for e in events if e.get("fouled_player") == player),
        "cards": [e["outcome"] for e in own if e["type"] == "card"],
        "moments": moments,
    }


def _moment(event, text):
    return {"event_id": event["id"], "clock": clock(event), "text": text}


# ---------- the whole picture ----------


def match_state(events, match_info, window_minutes=10):
    """The match right now: clock, score, xG, territory, passing and the recent trend."""
    if not events:
        return {"clock": "0'", "period": 1, "score": score(events)}
    latest = events[-1]
    recent = last_minutes(events, window_minutes)
    teams = [match_info["home"]["name"], match_info["away"]["name"]]
    return {
        "at_event": latest["id"],
        "clock": clock(latest),
        "period": latest["period"],
        "score": {match_info[s]["name"]: n for s, n in score(events).items()},
        "expected_goals": expected_goals(events, match_info)["teams"],
        "territory": territory(events, match_info),
        f"territory_last_{window_minutes}_min": territory(recent, match_info),
        "passing": {t: pass_quality(events, team=t) for t in teams},
        "control": control_vs_chaos(events),
        f"control_last_{window_minutes}_min": control_vs_chaos(recent),
        f"rhythm_last_{window_minutes}_min": rhythm(recent),
    }

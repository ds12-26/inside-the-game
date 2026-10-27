"""
Moment Scout: decides which events deserve the agents' attention.

Rules, not a model, so it is instant and never misses a goal. Each moment
carries the facts the agents may use, all computed from events up to that moment.
"""

from matchmind import stats

BIG_CHANCE_XG = stats.BIG_CHANCE_XG
CHECK_IN_EVERY_MIN = 15       # a "how's it going" summary this often
SWING_POINTS = 25             # field-tilt change over 10 minutes that counts as a momentum swing
PASSING_DROP_POINTS = 15      # pass accuracy over the last 5 minutes this far below the match so far
PASSING_CHECK_EVERY = 20      # events between passing checks
PASSING_COOLDOWN_MIN = 10     # at most one passing alert per team in this many minutes
EVENT_KINDS = ("goal", "own_goal", "big_chance", "card")
# Summaries where the favourite player is always worth a mention; otherwise only when involved.
FAVOURITE_KINDS = ("kick_off", "check_in", "momentum_swing", "period_end", "recap")
PERIOD_NAMES = {1: "first half", 2: "second half", 3: "first half of extra time", 4: "second half of extra time"}


def scout(events, match_info):
    """Every moment in the match, in order. `events` must be in event order."""
    moments, last_check_in, last_tilt, last_drop = [], 0, None, {}
    for i, e in enumerate(events):
        nxt = events[i + 1] if i + 1 < len(events) else None
        starts_period = i == 0 or events[i - 1]["period"] != e["period"]
        kind = "kick_off" if starts_period else _event_kind(e)
        if starts_period:
            last_check_in = e["minute"]
        if kind:
            moments.append(_moment(kind, events[:i + 1], match_info))
        minute = e["minute"]
        in_stoppage_time = minute + 1 > stats.PERIOD_END[e["period"]]
        if minute - last_check_in >= CHECK_IN_EVERY_MIN and not in_stoppage_time and nxt and nxt["period"] == e["period"]:
            last_check_in = minute
            so_far = events[:i + 1]
            tilt = stats.territory(stats.last_minutes(so_far, 10), match_info)[match_info["home"]["name"]]["field_tilt_pct"]
            swing = last_tilt is not None and abs(tilt - last_tilt) >= SWING_POINTS
            moments.append(_moment("momentum_swing" if swing else "check_in", so_far, match_info))
            last_tilt = tilt
        if i % PASSING_CHECK_EVERY == 0:
            for drop in passing_drops(events[:i + 1], match_info):
                if minute - last_drop.get(drop["team"], -99) >= PASSING_COOLDOWN_MIN:
                    last_drop[drop["team"]] = minute
                    moment = _moment("passing_drop", events[:i + 1], match_info)
                    moment["team"], moment["player"] = drop["team"], None
                    moment["facts"]["passing_drop"] = drop
                    moments.append(moment)
        if nxt is None or nxt["period"] != e["period"]:
            moments.append(_moment("period_end", events[:i + 1], match_info, final=nxt is None))
    return moments


def _event_kind(e):
    if e["type"] == "own_goal":
        return "own_goal"
    if e["type"] == "shot":
        if e["outcome"] == "goal":
            return "goal"
        if e["xg"] >= BIG_CHANCE_XG:
            return "big_chance"
    if e["type"] == "card":
        return "card"
    return None


def _moment(kind, so_far, match_info, final=False):
    e = so_far[-1]
    state = stats.match_state(so_far, match_info)
    facts = {
        "clock": state["clock"],
        "period": PERIOD_NAMES[e["period"]],
        "score": state["score"],
        "expected_goals": {t: {"xg": v["xg"], "shots": v["shots"], "on_target": v["on_target"]}
                           for t, v in state["expected_goals"].items()},
        "territory_last_10_min": {t: {"field_tilt_pct": v["field_tilt_pct"], "possession_pct": v["possession_pct"]}
                                  for t, v in state["territory_last_10_min"].items()},
        "control_last_10_min": state["control_last_10_min"]["state"],
    }
    facts["scores_so_far"] = scores_so_far(so_far, match_info)
    facts["leaders"] = leaders(facts["scores_so_far"], match_info)
    if kind in EVENT_KINDS:
        facts["event"] = ({k: e[k] for k in ("type", "outcome", "team", "player") if k in e}
                          | {k: e[k] for k in ("xg", "assist", "set_piece", "body_part", "credited_to") if k in e})
    if kind in ("goal", "big_chance", "card", "own_goal"):
        story = stats.player_story(so_far, match_info, e["player"])
        facts["player"] = {k: story[k] for k in ("player", "team", "position", "notes", "goals", "assists",
                                                  "shots", "saves", "cards")}
    if kind == "own_goal":
        facts["own_goal"] = {"scored_by": e["player"], "into_the_net_of": e["team"], "goal_counts_for": e["credited_to"],
                             "what_happened": own_goal_words(e)}
    if kind == "big_chance":
        nxt_save = e["outcome"] == "saved"
        facts["chance_in_plain_words"] = plain_xg(e["xg"])
        facts["keeper_saved"] = nxt_save
    if kind == "goal":
        facts["chance_in_plain_words"] = plain_xg(e["xg"])
    if kind == "period_end":
        facts["final_whistle"] = final
    return {"kind": kind, "event_id": e["id"], "clock": state["clock"], "team": e["team"],
            "player": e["player"], "facts": facts}


def plain_xg(xg):
    """An xG value as words a casual fan understands (fans never see decimals)."""
    pct = round(xg * 100)
    if xg >= 0.6:
        return f"a chance that is usually scored (about {pct} in 100)"
    if xg >= 0.4:
        return f"close to a 50-50 chance (about {pct} in 100)"
    if xg >= 0.2:
        return f"a real chance, scored about 1 time in {round(1 / xg)}"
    return f"a long shot, scored about 1 time in {round(1 / max(xg, 0.01))}"


def scores_so_far(events, match_info):
    """Every score the match has had up to now, e.g. ["0-0", "1-0", "1-1"] (home first)."""
    scores = ["0-0"]
    for i, e in enumerate(events):
        if e["type"] == "own_goal" or (e["type"] == "shot" and e["outcome"] == "goal"):
            s = stats.score(events[:i + 1])
            scores.append(f"{s['home']}-{s['away']}")
    return scores


def viewer_facts(moment, events, match_info, player):
    """The moment's facts plus how the viewer's favourite player is doing at that point."""
    if not player or (moment["kind"] not in FAVOURITE_KINDS and moment["player"] != player
                      and not (moment["kind"] in ("goal", "own_goal") and _keeper_of_team_conceding(moment, match_info, player))):
        return moment
    so_far = stats.events_until(events, moment["event_id"])
    story = stats.player_story(so_far, match_info, player)
    favourite = {k: story[k] for k in ("player", "team", "position", "notes", "touches", "goals", "assists",
                                        "shots", "saves", "tackles_won", "interceptions", "cards")}
    favourite["pass_accuracy_pct"] = story["passing"]["accuracy_pct"]
    favourite["recent_moments"] = story["moments"][-3:]
    favourite["involved_in_this_moment"] = moment["player"] == player
    return {**moment, "facts": {**moment["facts"], "favourite_player": favourite}}


def recap_moment(events, match_info):
    """The full-time recap as one last moment: the whole match's facts."""
    end = _moment("recap", events, match_info, final=True)
    goals = [{"clock": stats.clock(e), "team": e["team"] if e["type"] == "shot" else e["credited_to"],
              "scorer": e["player"], "own_goal": e["type"] == "own_goal", "assist": e.get("assist"),
              "score_after": e["score"]} | ({"what_happened": own_goal_words(e)} if e["type"] == "own_goal" else {})
             for e in events if e["type"] == "own_goal" or (e["type"] == "shot" and e["outcome"] == "goal")]
    xg = stats.expected_goals(events, match_info)
    end["facts"].update({
        "final_whistle": True,
        "after_extra_time": match_info.get("after_extra_time", False),
        "goals": goals,
        "expected_goals": xg["teams"],
        "best_chances": xg["best_chances"],
        "territory_whole_match": stats.territory(events, match_info),
        "passing": {t: stats.pass_quality(events, team=t) for t in (match_info["home"]["name"], match_info["away"]["name"])},
    })
    return end


def _keeper_of_team_conceding(moment, match_info, player):
    """True if `player` is the goalkeeper who just conceded."""
    for side in ("home", "away"):
        team = match_info[side]
        for p in team["players"]:
            if p["name"] == player and p["position"] == "GK":
                scorer_team = moment["facts"]["event"].get("credited_to") or moment["team"]
                return scorer_team != team["name"]
    return False


def passing_drops(so_far, match_info):
    """Teams whose pass accuracy over the last 5 minutes has fallen well below their match so far."""
    recent = stats.last_minutes(so_far, 5)
    drops = []
    for side in ("home", "away"):
        team = match_info[side]["name"]
        now, overall = stats.pass_quality(recent, team=team), stats.pass_quality(so_far, team=team)
        if now["attempted"] >= 8 and overall["accuracy_pct"] - now["accuracy_pct"] >= PASSING_DROP_POINTS:
            drops.append({"team": team, "pass_accuracy_pct_match_so_far": overall["accuracy_pct"],
                          "pass_accuracy_pct_last_5_min": now["accuracy_pct"], "passes_last_5_min": now["attempted"]})
    return drops


def leaders(scores, match_info):
    """Who has led, and how often the lead changed hands (an equaliser is not a lead change)."""
    home, away = match_info["home"]["name"], match_info["away"]["name"]
    led, changes, current = [], 0, None
    for s in scores:
        h, a = map(int, s.split("-"))
        leader = home if h > a else away if a > h else None
        if leader and leader not in led:
            led.append(leader)
        if leader and current and leader != current:
            changes += 1
        current = leader or current
    return {"teams_that_led": led, "lead_changes": changes}


def own_goal_words(e):
    """An own goal in one unambiguous sentence (models often put it in the wrong net)."""
    owner = e["team"] + ("'" if e["team"].endswith("s") else "'s")
    return f"{e['player']} of {e['team']} put the ball into {owner} own net; the goal counts for {e['credited_to']}."


def plain_words(facts):
    """Full-time facts for a fan: the story in words, no percentages or decimals to copy."""
    out = {k: v for k, v in facts.items()
           if k not in ("territory_whole_match", "territory_last_10_min", "passing", "expected_goals", "best_chances")}
    (home, h), (away, a) = [(t, v) for t, v in facts["territory_whole_match"].items()]
    words = []
    for team, other, share in ((home, away, h["possession_pct"]), (away, home, a["possession_pct"])):
        if share >= 65:
            words.append(f"{team} had the ball about two-thirds of the time.")
        elif share >= 55:
            words.append(f"{team} had more of the ball.")
    for team, other, tilt in ((home, away, h["field_tilt_pct"]), (away, home, a["field_tilt_pct"])):
        if tilt >= 70:
            words.append(f"{team} spent most of the match in {other}{chr(39) if other.endswith('s') else chr(39) + 's'} half.")
    xg = facts.get("expected_goals", {})
    if xg:
        (t1, x1), (t2, x2) = xg.items()
        words.append(f"{t1} had {x1['shots']} shots to {t2}{chr(39) if t2.endswith('s') else chr(39) + 's'} {x2['shots']}.")
        better = t1 if x1["xg"] > x2["xg"] else t2
        words.append(f"{better} created the better chances.")
    fav = facts.get("favourite_player")
    if fav and fav.get("pass_accuracy_pct") is not None:
        acc = fav["pass_accuracy_pct"]
        out["favourite_player"] = {k: v for k, v in fav.items() if k != "pass_accuracy_pct"}
        out["favourite_player"]["passing_in_words"] = (
            "almost every pass found a teammate" if acc >= 90 else
            "most passes found a teammate" if acc >= 75 else "passing was patchy")
    out["in_plain_words"] = words
    return out

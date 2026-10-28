"""
Tests for the Welcome agent, using a fake model (free, no Azure key needed).
Run with:  python -m pytest
"""

from matchmind.ingest.data import list_matches, load_match
from matchmind.personalize.welcome import welcome

MATCH = load_match("match_002")["match"]   # Red Lions vs Blue Sharks


def reply(**fields):
    """A fake model that always gives the same reply."""
    def ask(system, user):
        return {"greeting": "¡Bienvenido, tiburón!", **fields}
    return ask


def test_matches_are_listed_from_the_data_folder():
    assert {"match_id": "match_002", "home": "Red Lions", "away": "Blue Sharks"} in list_matches()


def test_quick_picks_alone_give_a_valid_profile_without_ai():
    result = welcome(MATCH, picks={"role": "analyst", "focus_metric": "xg"}, use_ai=False)
    assert result["ready"]
    assert result["profile"]["experience"] == "analyst_desk"
    assert result["profile"]["depth"] == "detailed"
    assert result["follow_ups"] == []


def test_free_text_is_read_by_the_model():
    ask = reply(role="fan", club="Blue Sharks", player="Moss", player_focus=True, language="es")
    result = welcome(MATCH, message="Soy de los Blue Sharks y sigo a Moss", ask=ask)
    profile = result["profile"]
    assert (profile["role"], profile["club"], profile["player"], profile["language"]) == \
        ("fan", "Blue Sharks", "Moss", "es")
    assert profile["player_focus"] and profile["experience"] == "fan_live"
    assert result["greeting"] == "¡Bienvenido, tiburón!" and result["greeting_source"] == "ai"


def test_names_are_matched_ignoring_case_and_nicknames():
    result = welcome(MATCH, message="x", ask=reply(role="FAN", club="sharks", player="moss"))
    assert result["profile"]["club"] == "Blue Sharks"
    assert result["profile"]["player"] == "Moss"


def test_invented_player_is_rejected_and_asked_again():
    result = welcome(MATCH, message="I love Messi", ask=reply(role="fan", club="Red Lions", player="Messi"))
    assert result["profile"]["player"] is None
    assert result["rejected"] == [{"field": "player", "value": "Messi"}]
    question = result["follow_ups"][0]
    assert question["field"] == "player" and "Messi" in question["question"]
    assert "Fox" in question["options"]
    assert result["greeting_source"] == "template"   # model greeting may mention the invented name


def test_quick_picks_win_over_the_model():
    result = welcome(MATCH, picks={"role": "broadcaster"}, message="I'm a fan", ask=reply(role="fan"))
    assert result["profile"]["role"] == "broadcaster"
    assert result["profile"]["experience"] == "studio"


def test_greeting_that_gives_away_the_score_is_replaced():
    ask = lambda system, user: {"role": "fan", "club": "Red Lions", "greeting": "Welcome! Red Lions won 3-2!"}
    result = welcome(MATCH, message="Red Lions fan", ask=ask)
    assert "3-2" not in result["greeting"]
    assert result["greeting_source"] == "template"


def test_model_failure_falls_back_to_keywords():
    def broken(system, user):
        raise TimeoutError("model unavailable")

    result = welcome(MATCH, message="Blue Sharks fan, follow Moss please, in Spanish", ask=broken)
    profile = result["profile"]
    assert result["source"] == "template" and "model unavailable" in result["fallback_reason"]
    assert (profile["role"], profile["club"], profile["player"], profile["language"]) == \
        ("fan", "Blue Sharks", "Moss", "es")
    assert profile["player_focus"]
    assert result["greeting"].startswith("¡Bienvenido!")


def test_missing_role_is_asked_first_in_the_viewers_language():
    result = welcome(MATCH, picks={"language": "French"}, use_ai=False)
    assert not result["ready"] and result["profile"]["experience"] is None
    assert result["follow_ups"][0]["field"] == "role"
    assert result["follow_ups"][0]["question"].startswith("Êtes-vous")


def test_fan_is_asked_for_a_club_until_they_answer_even_neutral():
    assert [q["field"] for q in welcome(MATCH, picks={"role": "fan"}, use_ai=False)["follow_ups"]] == ["club"]
    result = welcome(MATCH, picks={"role": "fan", "club": "neutral"}, use_ai=False)
    assert result["follow_ups"] == [] and result["profile"]["club"] is None


def test_player_focus_needs_a_player():
    result = welcome(MATCH, picks={"role": "fan", "club": "neutral", "player_focus": True}, use_ai=False)
    assert result["profile"]["player_focus"] is False


def test_hindi_is_understood_offline_and_greets_in_hindi():
    result = welcome(MATCH, message="Red Lions fan, Hindi please", use_ai=False)
    assert result["profile"]["language"] == "hi"
    assert result["greeting"].startswith("स्वागत है")


def test_play_by_play_in_hindi():
    from matchmind.render.playbyplay import line
    goal = next(e for e in load_match("match_002")["events"] if e["type"] == "shot" and e["outcome"] == "goal")
    assert line(goal, "hi") == "Fox का गोल!"

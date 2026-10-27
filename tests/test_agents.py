"""
Tests for the agent workflow and the Moment Scout, using fake agents (free, no Azure needed).
"""

import asyncio
from types import SimpleNamespace

from matchmind.agents import current_event, no_spoilers, write_card
from matchmind.data import load_match
from matchmind.moments import plain_xg, recap_moment, scout, viewer_facts

MATCH = load_match("match_002")
EVENTS, INFO = MATCH["events"], MATCH["match"]
MOMENTS = scout(EVENTS, INFO)
FOX_GOAL = next(m for m in MOMENTS if m["kind"] == "goal")
FAN = {"role": "fan", "language": "en", "club": "Red Lions", "player": "Fox"}


class FakeAgent:
    """Replies with the given outputs in turn and remembers every prompt."""

    def __init__(self, *outputs):
        self.outputs, self.prompts = list(outputs), []

    async def run(self, prompt, options=None):
        self.prompts.append(prompt)
        return SimpleNamespace(value=options["response_format"](**self.outputs.pop(0)))


def fakes(writer_outputs, verdicts):
    return {"fan": FakeAgent(*writer_outputs), "checker": FakeAgent(*verdicts)}


def run_card(fake_agents, moment=FOX_GOAL, mode="fan", viewer=FAN):
    return asyncio.run(write_card(fake_agents, "match_002", moment, mode, viewer))


def test_scout_finds_every_goal_and_period():
    kinds = [m["kind"] for m in MOMENTS]
    assert kinds.count("goal") + kinds.count("own_goal") == 5
    assert kinds.count("kick_off") == 4 and kinds.count("period_end") == 4


def test_moment_facts_only_know_the_past():
    assert FOX_GOAL["facts"]["score"] == {"Red Lions": 1, "Blue Sharks": 0}
    assert FOX_GOAL["facts"]["scores_so_far"] == ["0-0", "1-0"]


def test_own_goal_says_whose_net_it_went_into():
    own_goal = next(m for m in MOMENTS if m["kind"] == "own_goal")
    assert own_goal["facts"]["own_goal"] == {"scored_by": "Bell", "into_the_net_of": "Blue Sharks",
                                            "goal_counts_for": "Red Lions"}


def test_favourite_player_facts_only_when_relevant():
    card = next(m for m in MOMENTS if m["kind"] == "card" and m["player"] == "Ward")
    assert "favourite_player" not in viewer_facts(card, EVENTS, INFO, "Fox")["facts"]
    assert viewer_facts(FOX_GOAL, EVENTS, INFO, "Fox")["facts"]["favourite_player"]["goals"] == 1
    assert "favourite_player" in viewer_facts(FOX_GOAL, EVENTS, INFO, "Moss")["facts"]   # the keeper who conceded


def test_fans_get_chances_in_plain_words():
    assert plain_xg(0.26) == "a real chance, scored about 1 time in 4"
    assert "50-50" in plain_xg(0.54)


def test_approved_draft_becomes_a_card():
    card = run_card(fakes([{"text": "Fox scores!"}], [{"approved": True, "problems": []}]))
    assert card["content"] == {"text": "Fox scores!"} and card["source"] == "ai"
    assert card["fact_check"]["attempts"] == 1


def test_fact_checker_sends_a_wrong_draft_back_once():
    fake = fakes([{"text": "Fox scores again!"}, {"text": "Fox scores!"}],
                 [{"approved": False, "problems": ["this is Fox's first goal"]}, {"approved": True, "problems": []}])
    card = run_card(fake)
    assert card["content"] == {"text": "Fox scores!"} and card["fact_check"]["attempts"] == 2
    assert "this is Fox's first goal" in fake["fan"].prompts[1]          # the writer saw the problem


def test_twice_rejected_draft_falls_back_to_a_true_template():
    fake = fakes([{"text": "Fox scores again!"}, {"text": "Fox scores yet again!"}],
                 [{"approved": False, "problems": ["first goal"]}, {"approved": False, "problems": ["first goal"]}])
    card = run_card(fake)
    assert card["source"] == "template" and card["content"]["text"] == "28' Red Lions 1 Blue Sharks 0"


def test_code_checks_catch_a_wrong_score_without_asking_the_model():
    fake = fakes([{"text": "Fox makes it 2-0!"}, {"text": "Fox makes it 1-0!"}], [{"approved": True, "problems": []}])
    card = run_card(fake)
    assert card["content"]["text"] == "Fox makes it 1-0!"
    assert "2-0" in card["fact_check"]["history"][0]["problems"][0]
    assert len(fake["checker"].prompts) == 1                              # only the fixed draft reached it


def test_fans_never_see_decimals_or_xg():
    fake = fakes([{"text": "Fox scores from 0.26 xG!"}, {"text": "Fox buries a real chance!"}],
                 [{"approved": True, "problems": []}])
    assert run_card(fake)["content"]["text"] == "Fox buries a real chance!"


def test_model_failure_still_gives_a_card():
    class Broken:
        async def run(self, prompt, options=None):
            raise TimeoutError("model unavailable")
    card = run_card({"fan": Broken(), "checker": Broken()})
    assert card["source"] == "template" and "model unavailable" in card["fact_check"]["error"]


def test_tool_calls_cannot_look_past_the_current_moment():
    async def call(asked):
        context = SimpleNamespace(arguments={"match_id": "match_002", **asked})
        token = current_event.set(352)
        try:
            await no_spoilers(context, lambda: asyncio.sleep(0))
        finally:
            current_event.reset(token)
        return context.arguments["at_event"]
    assert asyncio.run(call({})) == 352                  # no at_event: capped at now, not the whole match
    assert asyncio.run(call({"at_event": 1600})) == 352  # asking for the future: capped
    assert asyncio.run(call({"at_event": 100})) == 100   # the past is fine


def test_recap_knows_every_goal_and_the_final_score():
    recap = recap_moment(EVENTS, INFO)
    assert [g["scorer"] for g in recap["facts"]["goals"]] == ["Fox", "Gray", "Reid", "Cruz", "Bell"]
    assert recap["facts"]["score"] == {"Red Lions": 3, "Blue Sharks": 2}


def test_ensemble_fans_out_to_three_views_and_fact_checks_the_merge():
    from matchmind.ensemble import ensemble_report

    view = {"title": "Red Lions win", "paragraphs": ["Red Lions won 3-2."]}
    report = {"title": "Red Lions edge it", "summary": "Red Lions won 3-2 after extra time.",
              "sections": [{"perspective": "The numbers", "text": "4.61 xG to 2.48."}]}
    wrong = {**report, "summary": "Red Lions won 4-2."}
    recap, checker = FakeAgent(view, view, view), FakeAgent({"approved": True, "problems": []})
    coordinator = FakeAgent(wrong, report)
    result = asyncio.run(ensemble_report("match_002", {"recap": recap, "checker": checker}, coordinator))
    assert set(result["views"]) == {"fan", "analyst", "broadcaster"}
    assert result["report"] == report and result["fact_check"]["attempts"] == 2   # 4-2 caught in code
    assert "4-2" in result["fact_check"]["history"][0]["problems"][0]


def test_passing_drop_alerts_the_director():
    drops = [m for m in MOMENTS if m["kind"] == "passing_drop"]
    assert len(drops) == 4 and all(m["team"] == "Blue Sharks" for m in drops)
    first = drops[0]["facts"]["passing_drop"]
    assert first["pass_accuracy_pct_match_so_far"] - first["pass_accuracy_pct_last_5_min"] >= 15

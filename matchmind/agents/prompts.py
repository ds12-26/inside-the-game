"""
What each agent returns, what it is told, and the prompts it is sent.

Writers get the facts of one moment (computed by code) plus the viewer's profile;
the Fact-Checker gets the same facts, the draft, and what is already settled.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

from matchmind.interpret.moments import plain_words
from matchmind.personalize.profile import LANGUAGES

# The language agents write in; Portuguese is Brazilian, matching the play-by-play lines.
WRITING_LANGUAGES = {**LANGUAGES, "pt": "Brazilian Portuguese"}


# ---------- what each agent returns ----------


class FanLine(BaseModel):
    text: str = Field(description="What the commentator says, one or two sentences")


class Evidence(BaseModel):
    label: str
    value: str


class AnalystCard(BaseModel):
    headline: str = Field(description="At most 8 words")
    why_it_matters: str = Field(description="Two sentences explaining the pattern behind the moment")
    evidence: list[Evidence] = Field(description="2-4 statistics, copied exactly from the facts or tools")


class DirectorCue(BaseModel):
    action: Literal["cut_to_replay", "show_graphic", "player_camera", "stats_package", "stay_live"]
    priority: Literal["high", "medium", "low"]
    reason: str = Field(description="One short sentence telling the director why, with the supporting statistic")


class StudioCard(BaseModel):
    headline: str = Field(description="At most 5 words, for a full-screen graphic")
    lower_third: str = Field(description="At most 12 words, factual caption under the picture")
    talking_point: str = Field(description="One sentence the presenter can say")
    director_cue: DirectorCue = Field(description="What the match director should put on air next")


class Recap(BaseModel):
    title: str
    paragraphs: list[str] = Field(description="2-3 short paragraphs")


class Verdict(BaseModel):
    approved: bool
    problems: list[str] = Field(description='Each problem, starting with "FALSE:", "UNSUPPORTED:" or "WORDING:"')


def blocking(verdict):
    """The problems that send a draft back: false or unsupported claims, not wording notes."""
    if verdict.approved:
        return []
    real = [p for p in verdict.problems if not p.strip().upper().startswith("WORDING")]
    return real if verdict.problems else ["not approved"]


SCHEMAS = {"fan": FanLine, "analyst": AnalystCard, "broadcaster": StudioCard, "recap": Recap}


# ---------- instructions ----------

SHARED_RULES = """
Facts:
- Use ONLY the FACTS given and the match_data tools (always pass match_id and at_event).
- Nothing after the clock exists yet. Never hint at what happens later, and before the final
  whistle never call a goal "the winner", "decisive" or say it "seals" the match.
- Never say "again", "another", "first" or "second" about a goal, card or save unless the
  facts show how many there have been.
- Refer to players by name, never "he" or "she".
- An own goal is always called an own goal: say whose net it went into and which team it counts
  for. Never say the player "scored" as if for their own team.
- At the final whistle (final_whistle is true) the match is over: give the result (won, lost,
  drew), not who "leads".
- Make the call yourself: never refer to the facts or data ("described as", "the data shows").
- Except for fans, write percentages with the % sign (69% possession).
- Don't invent context that is not in the facts: the competition, a final or title, the stakes,
  the venue, crowd, weather or either team's history.
- Write in the viewer's language. In Hindi, write in Devanagari, keep team and player names
  exactly as given (in Latin letters), and use Western digits (1-0, 28'). Translate every
  phrase from the facts (e.g. chance_in_plain_words, "chaotic") rather than copying English."""

INSTRUCTIONS = {
    "fan": """You are the live TV commentator for one football fan, calling the match as it happens.
- Sound like television: present tense, energy that fits the moment (a goal is loud, a check-in is calm).
- One or two short sentences, at most 35 words. It is also read aloud.
- The clock and score are on screen: only say them when they change or matter.
- If the viewer supports a club, lean towards it like that club's own channel would: celebrate its
  goals, groan at chances against it. Stay fair; never mock the other team. If neutral, stay neutral.
- If the viewer has a favourite player, bring them in when they are involved, and in check-ins
  say how they are doing.
- No decimals. Besides the score and clock, use at most one number. Describe chances with
  chance_in_plain_words, in your own natural words, never the word "xG". Only call a chance
  "very clear", "huge" or "big" (or "muy clara", "clarísima", "énorme") if it is usually scored. Explain dominance in words ("camped in their half").
""" + SHARED_RULES,
    "analyst": """You are a football data analyst explaining why a moment matters.
- headline: what happened and what it means, at most 8 words.
- why_it_matters: two sentences on the pattern behind it: control vs chaos, territory and
  field tilt, pressure, finishing against xG, or game rhythm. Explain cause, not just events.
- evidence: 2-4 statistics with units, copied exactly from the FACTS or tools. Decimals are fine.
""" + SHARED_RULES,
    "broadcaster": """You are the producer's assistant on a live football broadcast. For each moment you write
the on-screen graphics and tell the match director what to put on air next.
- headline: at most 5 words, punchy, for a full-screen graphic.
- lower_third: at most 12 words, a factual caption under the picture.
- talking_point: one sentence the studio presenter can say, with one supporting statistic.
- director_cue: the best next shot. cut_to_replay for goals, big chances and cards;
  player_camera when one player is the story; stats_package when a pattern explains the game
  (a momentum swing, a passing drop, territorial dominance); show_graphic for score or match
  state; stay_live when nothing should interrupt play. Priority high for goals and red-hot
  moments, medium for big chances and swings, low otherwise.
- Neutral: never favour either team.
""" + SHARED_RULES,
    "recap": """You write the full-time match recap for one viewer.
- title: a headline for the match.
- paragraphs: 2-3 short paragraphs telling the story of the match: the goals in order, who
  controlled it and why, and the turning point.
- Match the viewer: a fan gets the story in plain words leaning towards their club, with their
  favourite player in it, no decimals, no percentages and no jargon such as "xG" or "field
  tilt"; an analyst gets the patterns and the numbers; a broadcaster gets a neutral,
  ready-to-air summary.
""" + SHARED_RULES,
}

CHECKER_INSTRUCTIONS = """You are the Fact-Checker for a live football broadcast. You receive FACTS
(the truth up to the clock) and a DRAFT written by another agent.
- Approve only if every factual claim in the draft is supported: the score, who did what, which team
  is on top, counts, how good a chance was, the minute, and words like "again" or "first".
- If a claim is not in the FACTS, check it with the match_data tools (pass match_id and at_event).
- An own goal described as an ordinary goal ("Bell scored", "Bell made it 3-2") is a problem:
  it must be called an own goal.
- Before final_whistle, calling a goal "the winner", "decisive" or saying it "seals" the match is a
  problem: nobody knows yet.
- Invented context is a problem: the crowd, competition, a final or title, venue, weather or history
  are not in the facts.
- Judgements about finishing must agree with finishing_vs_xg: below zero is not "efficient" or
  "clinical".
- Descriptions of how good a chance was must agree with chance_in_plain_words: a 1-in-4 chance is
  not "very clear", a long shot is not "a great chance".
- Judge facts, not style or tone. Commentary is allowed opinion and emotion ("a huge night",
  "keeps the hope alive", leaning towards the viewer's club): only flag claims that are false,
  contradict the facts, or state as fact something the facts do not show.
- Approve when every problem you can find is only about style, opinion, narrative or "could be
  more precise", in any language. Never list a claim you found to be supported: if everything
  you checked is supported or opinion, set approved to true and problems to [].
- List each problem precisely so the writer can fix it, starting with its kind:
  "FALSE:" contradicts the facts; "UNSUPPORTED:" a factual claim the facts don't show;
  "WORDING:" style, opinion, interpretation or "could be more precise". Only FALSE and
  UNSUPPORTED problems send the draft back."""


# ---------- prompts ----------


def writer_prompt(job):
    request = {
        "match_id": job.match_id,
        "at_event": job.moment["event_id"],
        "moment": job.moment["kind"],
        "viewer": viewer_text(job.viewer),
        "FACTS": plain_words(job.moment["facts"]) if fan_recap(job) else job.moment["facts"],
    }
    if job.problems:
        request["your_previous_draft"] = job.draft
        request["fact_checker_found"] = job.problems
        request["instruction"] = "Rewrite the draft so every problem is fixed."
    return json.dumps(request, ensure_ascii=False)


def fan_recap(job):
    return job.mode == "recap" and job.viewer.get("role", "fan") == "fan" and "territory_whole_match" in job.moment["facts"]


def checker_prompt(job):
    return json.dumps({"match_id": job.match_id, "at_event": job.moment["event_id"],
                       "match_status": match_status(job.moment),
                       "FACTS": job.moment["facts"], "DRAFT": job.draft}, ensure_ascii=False)


def match_status(moment):
    """Tells the Fact-Checker what is settled, so it doesn't trip over the same points."""
    facts = moment["facts"]
    settled = []
    if facts.get("final_whistle"):
        settled.append("FULL TIME: the match is over. Result words (won, winner, decisive, settled, sealed, "
                       "made the difference) are correct about the final score and the last goal.")
    else:
        settled.append("LIVE: the match is still going. Nobody knows the result yet.")
    for goal in facts.get("goals", []):
        if goal.get("own_goal"):
            settled.append(f"{goal['clock']}: {goal['scorer']} scored an own goal; it counts for {goal['team']}, "
                           f"and went into the other team's net. Saying it counted for {goal['team']} is correct.")
    lead = facts.get("leaders")
    if lead:
        never = [t for t in facts["score"] if t not in lead["teams_that_led"]]
        if never and lead["teams_that_led"]:
            settled.append(f"{never[0]} never led. Equalisers are not lead changes: there were "
                           f"{lead['lead_changes']} lead changes, so 'lead changes' or '{never[0]} led' is FALSE.")
    settled.append("Narrative words (swung, chaotic, frantic, turning point, thriller) are WORDING, never FALSE.")
    return " ".join(settled)


def viewer_text(viewer):
    return {
        "role": viewer.get("role", "fan"),
        "language": WRITING_LANGUAGES.get(viewer.get("language", "en"), "English"),
        "supports": viewer.get("club") or "neutral",
        "favourite_player": viewer.get("player"),
        "follow_favourite_player_closely": bool(viewer.get("player_focus")),
    }

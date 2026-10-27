"""
The match agents and the workflow that runs them, built with Microsoft Agent
Framework on a model deployed in a Microsoft Foundry project.

For every moment the Moment Scout finds:

    Writer (Narrator for fans, Analyst, or Studio Producer for broadcasters)
        -> Fact-Checker -- approved --> card on screen
                        -- problems --> back to the Writer once, then a safe template

Writers and the Fact-Checker get facts computed by code, and can ask the Match
Data MCP server for more. A middleware caps every tool call at the current
moment, so no agent can see what happens later in the match (no spoilers).
"""

import contextvars
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from agent_framework import (Agent, Executor, MCPStdioTool, MCPStreamableHTTPTool, WorkflowBuilder,
                             WorkflowContext, function_middleware, handler)
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from matchmind.guards import check_script, scorelines
from matchmind.moments import plain_words
from matchmind.profile import LANGUAGES

load_dotenv()

# The language agents write in; Portuguese is Brazilian, matching the play-by-play lines.
WRITING_LANGUAGES = {**LANGUAGES, "pt": "Brazilian Portuguese"}

MAX_ATTEMPTS = 2
MAX_RECAP_ATTEMPTS = 3        # the recap is one long piece, worth an extra try
FAN_MAX_WORDS = 45

# The event ID of the moment being worked on; tool calls may not look past it.
current_event = contextvars.ContextVar("current_event", default=None)


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


# ---------- model, tools and the no-spoiler guard ----------


def chat_client():
    """The Foundry project model, signed in with Azure CLI locally or managed identity in Azure."""
    from agent_framework_foundry import FoundryChatClient
    from azure.identity import DefaultAzureCredential

    return FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                             model=os.environ["FOUNDRY_MODEL"], credential=DefaultAzureCredential())


def match_tools():
    """The Match Data MCP server: over HTTP when MATCH_MCP_URL is set, otherwise as a local subprocess."""
    if os.environ.get("MATCH_MCP_URL"):
        return MCPStreamableHTTPTool(name="match_data", url=os.environ["MATCH_MCP_URL"])
    return MCPStdioTool(name="match_data", command=sys.executable, args=["-m", "matchmind.mcp_server", "--stdio"])


@function_middleware
async def no_spoilers(context, call_next):
    """Cap every tool call at the moment being described, whatever the agent asked for."""
    now = current_event.get()
    args = context.arguments
    if now is not None and isinstance(args, dict) and "match_id" in args:
        asked = args.get("at_event")
        args["at_event"] = now if asked is None else min(int(asked), now)
    await call_next()


def build_agents(client=None, tools=None):
    """One Agent Framework agent per job, all sharing the model and the MCP tools."""
    client = client or chat_client()
    make = lambda name, instructions: Agent(client=client, name=name, instructions=instructions,
                                            tools=tools, middleware=[no_spoilers])
    agents = {mode: make(f"{mode}_writer", text) for mode, text in INSTRUCTIONS.items()}
    agents["checker"] = make("fact_checker", CHECKER_INSTRUCTIONS)
    return agents


# ---------- the workflow ----------


@dataclass
class Job:
    """One moment being written for one viewer, as it moves between the agents."""
    match_id: str
    moment: dict
    mode: str                     # fan, analyst, broadcaster or recap
    viewer: dict                  # club, player, player_focus, language
    attempts: int = 0
    draft: dict | None = None
    problems: list = field(default_factory=list)
    history: list = field(default_factory=list)


class Writer(Executor):
    def __init__(self, agent):
        super().__init__(id="writer")
        self.agent = agent

    @handler
    async def write(self, job: Job, ctx: WorkflowContext[Job]) -> None:
        reply = await self.agent.run(writer_prompt(job), options={"response_format": SCHEMAS[job.mode]})
        job.draft = reply.value.model_dump()
        job.attempts += 1
        await ctx.send_message(job)


class FactChecker(Executor):
    def __init__(self, agent):
        super().__init__(id="fact_checker")
        self.agent = agent

    @handler
    async def check(self, job: Job, ctx: WorkflowContext[Job, dict]) -> None:
        problems = rule_problems(job)
        if not problems:
            reply = await self.agent.run(checker_prompt(job), options={"response_format": Verdict})
            problems = blocking(reply.value)
            notes = [p for p in reply.value.problems if p not in problems]
        else:
            notes = []
        job.history.append({"draft": job.draft, "problems": problems, "notes": notes})
        if not problems:
            await ctx.yield_output(card(job, approved=True))
        elif job.attempts < (MAX_RECAP_ATTEMPTS if job.mode == "recap" else MAX_ATTEMPTS):
            job.problems = problems
            await ctx.send_message(job)
        else:
            await ctx.yield_output(card(job, approved=False))


def build_workflow(writer_agent, checker_agent):
    writer, checker = Writer(writer_agent), FactChecker(checker_agent)
    return (WorkflowBuilder(name="moment_to_card", start_executor=writer)
            .add_edge(writer, checker)
            .add_edge(checker, writer)
            .build())


async def write_card(agents, match_id, moment, mode, viewer):
    """Run one moment through the Writer and Fact-Checker; always returns a card."""
    token = current_event.set(moment["event_id"])
    try:
        job = Job(match_id=match_id, moment=moment, mode=mode, viewer=viewer)
        result = await build_workflow(agents[mode], agents["checker"]).run(job)
        return result.get_outputs()[-1]
    except Exception as error:
        return fallback_card(moment, mode, viewer, reason=str(error) or type(error).__name__)
    finally:
        current_event.reset(token)


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


# ---------- checks done in code before the Fact-Checker agent ----------


def draft_text(draft, skip=()):
    """All the words in a draft, whatever its shape; separate fields never run together."""
    parts = []
    for key, value in draft.items():
        if key in skip:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            parts.append(draft_text(value))
        elif isinstance(value, list):
            parts += [v if isinstance(v, str) else draft_text(v) for v in value]
    return " | ".join(parts)


# Common short words, to tell Spanish, French and Portuguese text from English.
STOPWORDS = {
    "es": {"el", "los", "las", "del", "que", "con", "para", "por", "en", "un", "una", "y", "es"},
    "fr": {"le", "les", "des", "du", "que", "avec", "pour", "est", "et", "un", "une", "dans", "sur"},
    "pt": {"o", "os", "do", "da", "que", "com", "para", "por", "em", "um", "uma", "e", "no", "na"},
}


def wrong_language(text, language):
    """True if the text reads as English rather than the viewer's language."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    english = sum(w in {"the", "and", "with", "for", "is", "are", "has", "have", "on", "of", "to", "in"} for w in words)
    target = sum(w in STOPWORDS[language] for w in words)
    return english >= 3 and english > target


def completed_pass_problems(text, facts):
    """'838 passes completed' when 838 were attempted: the number completed must match the data."""
    passing = facts.get("passing") or {}
    completed = {v["completed"] for v in passing.values()}
    if not completed:
        return []
    claims = re.findall(r"(\d+)\s+(?:passes\s+completed|completed\s+passes)|complet\w*\s+(\d+)\s+(?:of\s+\d+\s+)?passes", text, re.IGNORECASE)
    wrong = sorted({int(a or b) for a, b in claims} - completed)
    return [f"FALSE: {n} passes were not completed; completed passes were {sorted(completed)}" for n in wrong]


def own_net_problems(text, facts):
    """An own goal said to go into the wrong team's net ("into Red Lions' own net")."""
    own_goals = [g for g in facts.get("goals", []) if g.get("own_goal")]
    if facts.get("own_goal"):
        own_goals.append({"team": facts["own_goal"]["goal_counts_for"]})
    return [f"FALSE: the own goal went into the other team's net, not {g['team']}'s"
            for g in own_goals if re.search(re.escape(g["team"]) + r"[’']?s?\s+(?:own\s+)?net", text)]


def devanagari_share(text):
    """Share of words in Devanagari, skipping names (capitalised Latin words) and numbers."""
    words = [w for w in re.findall(r"\w+", text) if not w.isdigit() and not (w[0].isupper() and w.isascii())]
    hindi = sum(any("DEVANAGARI" in unicodedata.name(c, "") for c in w) for w in words)
    return hindi / len(words) if words else 1


def rule_problems(job):
    """Problems any reader would spot, found without a model."""
    text, problems = draft_text(job.draft), []
    try:
        check_script(text, job.viewer.get("language", "en"))
    except ValueError as error:
        problems.append(str(error))
    facts = job.moment["facts"]
    real = [sorted(map(int, s.split("-"))) for s in facts["scores_so_far"]]
    for pair in scorelines(text):
        if sorted(pair) not in real:
            problems.append(f"mentions the score {pair[0]}-{pair[1]}, which this match has not had; "
                            f"it is {'-'.join(map(str, facts['score'].values()))}")
    for_fan = job.mode == "fan" or (job.mode == "recap" and job.viewer.get("role", "fan") == "fan")
    prose = draft_text(job.draft, skip=("evidence",))      # evidence chips are label/value pairs
    problems += own_net_problems(prose, job.moment["facts"])
    problems += completed_pass_problems(prose, job.moment["facts"])
    if not for_fan and re.search(r"\b\d{1,3}\s+(?:possession|field tilt|pass accuracy|accuracy)\b", prose, re.IGNORECASE):
        problems.append("write percentages with the % sign, e.g. 69% possession")
    if re.search(r"\d\s*%\s*(?:of\s+)?(?:the\s+)?xG|xG\s+(?:of\s+)?\d+\s*%", text, re.IGNORECASE):
        problems.append("FALSE: xG is not a percentage (e.g. 0.81 xG, not 81% xG)")
    language = job.viewer.get("language", "en")
    if language == "en" and re.search(r"\b(he|his|him|himself|she|her|hers|herself)\b", prose, re.IGNORECASE):
        problems.append("refer to players by name, not he/his/she/her: the data doesn't record genders")
    if language in STOPWORDS and wrong_language(prose, language):
        problems.append(f"write in {WRITING_LANGUAGES[language]}, not English")
    if job.viewer.get("language") == "hi" and devanagari_share(text) < 0.5:
        problems.append("the viewer chose Hindi: write in Hindi (Devanagari), keeping only names in Latin letters")
    if job.mode == "fan" or (job.mode == "recap" and job.viewer.get("role", "fan") == "fan"):
        if re.search(r"\d[.,]\d", text):
            problems.append("fans should not see decimals; describe the chance in words")
        if re.search(r"\bxG\b", text, re.IGNORECASE):
            problems.append("fans should not see the term xG; describe the chance in words")
        if re.search(r"\d\s*%|field tilt", text, re.IGNORECASE):
            problems.append("fans should not see percentages or analyst terms; say it in plain words")
        if job.mode == "fan" and len(text.split()) > FAN_MAX_WORDS:
            problems.append(f"too long to read aloud: keep it under {FAN_MAX_WORDS} words")
    return problems


# ---------- cards ----------


def card(job, approved):
    return {
        "event_id": job.moment["event_id"],
        "clock": job.moment["clock"],
        "kind": job.moment["kind"],
        "mode": job.mode,
        "language": job.viewer.get("language", "en"),
        "content": job.draft if approved else fallback_content(job.moment, job.mode, job.viewer.get("language", "en")),
        "source": "ai" if approved else "template",
        "fact_check": {"approved": approved, "attempts": job.attempts, "history": job.history},
    }


def fallback_card(moment, mode, viewer, reason):
    return {
        "event_id": moment["event_id"], "clock": moment["clock"], "kind": moment["kind"], "mode": mode,
        "language": viewer.get("language", "en"), "content": fallback_content(moment, mode, viewer.get("language", "en")),
        "source": "template", "fact_check": {"approved": False, "attempts": 0, "error": reason},
    }


# When the agents can't produce an approved card, the broadcaster still gets the right shot.
FALLBACK_CUES = {
    "goal": ("GOAL", "cut_to_replay", "high", "A goal changes the score: replay it."),
    "own_goal": ("OWN GOAL", "cut_to_replay", "high", "An own goal changes the score: replay it."),
    "big_chance": ("BIG CHANCE", "cut_to_replay", "medium", "A big chance: worth a replay."),
    "card": ("BOOKING", "cut_to_replay", "medium", "A booking: show the incident."),
    "momentum_swing": ("MOMENTUM SWING", "stats_package", "medium", "The balance of play has shifted: show the territory graphic."),
    "passing_drop": ("PASSING DROP", "stats_package", "medium", "A team's passing has dropped sharply: show the passing graphic."),
    "check_in": ("MATCH UPDATE", "show_graphic", "low", "Show the score and match state."),
    "kick_off": ("KICK-OFF", "show_graphic", "medium", "Play is starting: show the score and clock."),
    "period_end": ("END OF PERIOD", "show_graphic", "high", "The period is over: show the score."),
}


FULL_TIME = {"en": "Full time", "es": "Final", "fr": "Fin du match", "pt": "Fim de jogo", "hi": "फ़ुल टाइम"}


def fallback_recap(moment, language):
    """The result and the goals, built from the data: always true, in any language."""
    facts = moment["facts"]
    (home, h), (away, a) = facts["score"].items()
    goals = " · ".join(f"{g['scorer']} {g['clock']}" + (" (o.g.)" if g["own_goal"] else "")
                       for g in facts.get("goals", []))
    return {"title": f"{FULL_TIME.get(language, 'Full time')}: {home} {h}–{a} {away}",
            "paragraphs": [f"⚽ {goals}"] if goals else []}


def fallback_content(moment, mode, language="en"):
    """A plain, always-true line for when the agents can't produce an approved one."""
    facts = moment["facts"]
    if mode == "recap":
        return fallback_recap(moment, language)
    score = " ".join(f"{team} {goals}" for team, goals in facts["score"].items())
    line = f"{moment['clock']} {score}"
    headline, action, priority, reason = FALLBACK_CUES.get(moment["kind"], ("UPDATE", "stay_live", "low", ""))
    if moment["kind"] == "period_end" and facts.get("final_whistle"):
        headline = "FULL TIME"
    return {
        "fan": {"text": line},
        "analyst": {"headline": line, "why_it_matters": "", "evidence": []},
        "broadcaster": {"headline": headline, "lower_third": line, "talking_point": "",
                        "director_cue": {"action": action, "priority": priority, "reason": reason}},
    }[mode]

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
import os
import sys
from dataclasses import dataclass, field

from agent_framework import (Agent, Executor, MCPStdioTool, MCPStreamableHTTPTool, WorkflowBuilder,
                             WorkflowContext, function_middleware, handler)
from dotenv import load_dotenv

from matchmind.agents.checks import rule_problems
from matchmind.agents.prompts import (CHECKER_INSTRUCTIONS, INSTRUCTIONS, SCHEMAS, Verdict, blocking,
                                      checker_prompt, writer_prompt)

load_dotenv()

MAX_ATTEMPTS = 2
MAX_RECAP_ATTEMPTS = 3        # the recap is one long piece, worth an extra try

# The event ID of the moment being worked on; tool calls may not look past it.
current_event = contextvars.ContextVar("current_event", default=None)


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
    return MCPStdioTool(name="match_data", command=sys.executable, args=["-m", "matchmind.mcp.server", "--stdio"])


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

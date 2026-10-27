"""
The full-time ensemble report: concurrent orchestration with Microsoft Agent Framework.

    full-time facts --fan out--> Narrator view  --+
                             --> Analyst view   --+--fan in--> Coordinator --> Fact-Checker
                             --> Broadcast view --+                 ^ one rewrite |

The three specialists write the match from their own angle at the same time; the
Coordinator merges them into one multi-perspective report, which the Fact-Checker
verifies, because merging is exactly where new mistakes creep in.

Usage:
    python -m matchmind.ensemble
"""

import argparse
import asyncio
import json
from dataclasses import dataclass

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler
from pydantic import BaseModel, Field

from matchmind.agents import (MAX_RECAP_ATTEMPTS, Job, Recap, Verdict, blocking, build_agents, chat_client,
                              checker_prompt, current_event, match_tools, no_spoilers, rule_problems)
from matchmind.commentary import RUNS_DIR
from matchmind.data import load_match
from matchmind.moments import recap_moment

PERSPECTIVES = {
    "fan": "From the stands",
    "analyst": "The numbers",
    "broadcaster": "The broadcast package",
}

COORDINATOR_INSTRUCTIONS = """You are the editor combining three specialists' full-time reports into one
multi-perspective match report: a fan's view, an analyst's view and a broadcaster's view.
- title: one headline for the whole match.
- summary: one paragraph everyone can read: the result, the goals in order and the turning point.
- sections: keep each specialist's angle, tightened to 2-4 sentences each. Do not blend them into
  one voice: the fan section stays emotional, the analyst section keeps the numbers, the broadcast
  section stays neutral and ready to air.
- Use only what the specialists wrote and the FACTS. When they disagree, the FACTS win.
- Don't invent context: the competition, a final or title, the venue, crowd, weather or history.
- Refer to players by name, never "he" or "she"."""


class Section(BaseModel):
    perspective: str = Field(description="One of: From the stands, The numbers, The broadcast package")
    text: str


class EnsembleReport(BaseModel):
    title: str
    summary: str
    sections: list[Section]


@dataclass
class Brief:
    match_id: str
    moment: dict


@dataclass
class View:
    role: str
    recap: dict


class Dispatcher(Executor):
    """Hands the same full-time facts to every specialist."""

    @handler
    async def dispatch(self, brief: Brief, ctx: WorkflowContext[Brief]) -> None:
        await ctx.send_message(brief)


class Specialist(Executor):
    """Writes the match from one perspective, with the recap agent told whose view it is."""

    def __init__(self, role, agent):
        super().__init__(id=f"{role}_view")
        self.role, self.agent = role, agent

    @handler
    async def write(self, brief: Brief, ctx: WorkflowContext[View]) -> None:
        prompt = json.dumps({"match_id": brief.match_id, "at_event": brief.moment["event_id"],
                             "viewer": {"role": self.role, "language": "English", "supports": "neutral"},
                             "FACTS": brief.moment["facts"]}, ensure_ascii=False)
        reply = await self.agent.run(prompt, options={"response_format": Recap})
        await ctx.send_message(View(self.role, reply.value.model_dump()))


class Coordinator(Executor):
    """Merges the views, then has the Fact-Checker verify the merged report (one rewrite allowed)."""

    def __init__(self, agent, checker, brief):
        super().__init__(id="coordinator")
        self.agent, self.checker, self.brief = agent, checker, brief

    @handler
    async def merge(self, views: list[View], ctx: WorkflowContext[None, dict]) -> None:
        request = {"FACTS": self.brief.moment["facts"],
                   "specialists": {PERSPECTIVES[v.role]: v.recap for v in views}}
        history = []
        for attempt in range(1, MAX_RECAP_ATTEMPTS + 1):
            reply = await self.agent.run(json.dumps(request, ensure_ascii=False),
                                         options={"response_format": EnsembleReport})
            report = reply.value.model_dump()
            job = Job(self.brief.match_id, self.brief.moment, "ensemble", {"role": "broadcaster"}, draft=report)
            problems = rule_problems(job)
            if not problems:
                verdict = await self.checker.run(checker_prompt(job), options={"response_format": Verdict})
                problems = blocking(verdict.value)
            history.append({"draft": report, "problems": problems})
            if not problems:
                break
            request |= {"your_previous_draft": report, "fact_checker_found": problems,
                        "instruction": "Rewrite the report so every problem is fixed."}
        await ctx.yield_output({
            "report": report,
            "views": {v.role: v.recap for v in views},
            "fact_check": {"approved": not problems, "attempts": attempt, "history": history},
        })


def build_ensemble(agents, coordinator_agent, brief):
    dispatcher = Dispatcher(id="dispatcher")
    specialists = [Specialist(role, agents["recap"]) for role in PERSPECTIVES]
    coordinator = Coordinator(coordinator_agent, agents["checker"], brief)
    return (WorkflowBuilder(name="full_time_ensemble", start_executor=dispatcher)
            .add_fan_out_edges(dispatcher, specialists)
            .add_fan_in_edges(specialists, coordinator)
            .build())


async def ensemble_report(match_id, agents, coordinator_agent):
    match = load_match(match_id)
    brief = Brief(match_id, recap_moment(match["events"], match["match"]))
    token = current_event.set(brief.moment["event_id"])
    try:
        result = await build_ensemble(agents, coordinator_agent, brief).run(brief)
        return result.get_outputs()[-1]
    finally:
        current_event.reset(token)


def coordinator(client=None, tools=None):
    return Agent(client=client or chat_client(), name="coordinator", instructions=COORDINATOR_INSTRUCTIONS,
                 tools=tools, middleware=[no_spoilers])


async def main():
    parser = argparse.ArgumentParser(description="Write the full-time ensemble report.")
    parser.add_argument("--match", default="match_002")
    args = parser.parse_args()
    tools = match_tools()
    async with tools:
        client = chat_client()
        result = await ensemble_report(args.match, build_agents(client, tools), coordinator(client, tools))
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{args.match}-ensemble.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"ensemble report -> {path} (approved: {result['fact_check']['approved']}, "
          f"attempts: {result['fact_check']['attempts']})")


if __name__ == "__main__":
    asyncio.run(main())

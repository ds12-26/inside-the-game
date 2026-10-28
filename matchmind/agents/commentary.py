"""
Runs a whole match through the agents for one viewer: every moment the Moment
Scout finds, then the full-time recap. Moments are independent (each only sees
the match up to its own event), so they run in parallel.

Saved runs in data/runs/ let the demo replay instantly without calling the model.

Usage:
    python -m matchmind.agents.commentary --role fan --club "Blue Sharks" --player Moss --focus --language es
    python -m matchmind.agents.commentary --role analyst
"""

import argparse
import asyncio
import json
from pathlib import Path

from matchmind.agents import build_agents, match_tools, write_card
from matchmind.ingest.data import load_match
from matchmind.interpret.moments import recap_moment, scout, viewer_facts

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "runs"


def run_name(match_id, viewer):
    parts = [match_id, viewer["role"], viewer.get("language", "en"), viewer.get("club") or "neutral"]
    if viewer.get("player"):
        parts.append(viewer["player"])
    return "-".join(p.lower().replace(" ", "_") for p in parts)


async def run_match(match_id, viewer, agents, concurrency=8):
    """Cards for every moment of the match plus the recap, in match order."""
    match = load_match(match_id)
    events, info = match["events"], match["match"]
    moments = scout(events, info) + [recap_moment(events, info)]
    limit = asyncio.Semaphore(concurrency)

    async def one(moment):
        mode = "recap" if moment["kind"] == "recap" else viewer["role"]
        async with limit:
            return await write_card(agents, match_id, viewer_facts(moment, events, info, viewer.get("player")),
                                    mode, viewer)

    return await asyncio.gather(*(one(m) for m in moments))


async def main():
    parser = argparse.ArgumentParser(description="Write a viewer's commentary for a whole match.")
    parser.add_argument("--match", default="match_002")
    parser.add_argument("--role", choices=["fan", "analyst", "broadcaster"], default="fan")
    parser.add_argument("--language", default="en")
    parser.add_argument("--club")
    parser.add_argument("--player")
    parser.add_argument("--focus", action="store_true", help="follow the favourite player closely")
    args = parser.parse_args()
    viewer = {"role": args.role, "language": args.language, "club": args.club,
              "player": args.player, "player_focus": args.focus}

    tools = match_tools()
    async with tools:
        cards = await run_match(args.match, viewer, build_agents(tools=tools))

    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{run_name(args.match, viewer)}.json"
    path.write_text(json.dumps({"match_id": args.match, "viewer": viewer, "cards": cards}, indent=2, ensure_ascii=False))
    rewritten = sum(c["fact_check"]["attempts"] > 1 for c in cards)
    fallback = sum(c["source"] == "template" for c in cards)
    print(f"{len(cards)} cards -> {path}  (rewritten after fact-check: {rewritten}, template fallback: {fallback})")


if __name__ == "__main__":
    asyncio.run(main())

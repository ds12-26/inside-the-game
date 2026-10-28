"""
The web API and the page that serves each viewer's experience.

    GET  /                          the app (web/index.html)
    GET  /api/matches               match picker
    GET  /api/match/{id}            teams and squads (never the result)
    POST /api/welcome               Welcome agent: picks and/or free text -> profile and follow-ups
    GET  /api/live/{id}?...         Server-Sent Events: the match replayed live, with play-by-play,
                                    live stats and fact-checked agent cards for this viewer
    GET  /api/report/{id}           the full-time ensemble report

Cards come from a saved run when one exists for this viewer (instant, reliable for demos);
otherwise the agents write them live as each moment happens.

Usage:
    uvicorn matchmind.render.api:app --port 8000
"""

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from matchmind.ingest import data

from matchmind.interpret import stats

from matchmind.render import playbyplay
from matchmind.agents.commentary import RUNS_DIR, run_name
from matchmind.interpret.moments import EVENT_KINDS, recap_moment, scout, viewer_facts
from matchmind.ingest.replay import highlights
from matchmind.personalize.welcome import welcome

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
STATS_EVERY = 10          # events between live stats updates
CARD_WAIT_S = 30          # live play waits this long at a moment for its commentary, so words match the pitch
MAX_LIVE_MATCHES = int(os.environ.get("MAX_LIVE_MATCHES", "2"))   # caps model cost on a public URL
live_matches = 0

app = FastAPI(title="Inside the Game")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class WelcomeRequest(BaseModel):
    match_id: str = "match_002"
    picks: dict = {}
    message: str = ""


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/matches")
def matches():
    return data.list_matches()


@app.get("/api/match/{match_id}")
def match(match_id: str):
    info = _load(match_id)["match"]
    return {"match_id": match_id,
            "teams": {s: {k: info[s][k] for k in ("name", "short", "players")} for s in ("home", "away")}}


@app.post("/api/welcome")
async def welcome_viewer(request: WelcomeRequest):
    info = _load(request.match_id)["match"]
    return await asyncio.to_thread(welcome, info, request.picks, request.message)


@app.get("/api/report/{match_id}")
def report(match_id: str):
    path = RUNS_DIR / f"{match_id}-ensemble.json"
    if not path.exists():
        raise HTTPException(404, "No ensemble report yet: run python -m matchmind.agents.ensemble")
    return json.loads(path.read_text())


@app.get("/api/live/{match_id}")
async def live(request: Request, match_id: str, role: str = "fan", language: str = "en", club: str | None = None,
               player: str | None = None, focus: bool = False, speed: float = 1, start_after: int = 0,
               countdown: float = 0):
    viewer = {"role": role, "language": language, "club": club or None, "player": player or None,
              "player_focus": focus}
    return StreamingResponse(_live(request, match_id, viewer, speed, start_after, min(countdown, 10)),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _load(match_id):
    try:
        return data.load_match(match_id)
    except FileNotFoundError:
        raise HTTPException(404, f"No match {match_id}")


def _sse(kind, payload):
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _saved_cards(match_id, viewer):
    path = RUNS_DIR / f"{run_name(match_id, viewer)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())["cards"]


def _nearest_saved(match_id, viewer):
    """A saved run for the same role and language, used when too many matches are being written live."""
    for path in sorted(RUNS_DIR.glob(f"{match_id}-{viewer['role']}-{viewer['language']}-*.json")):
        return json.loads(path.read_text())["cards"]
    return None


def _pitch_event(e, language):
    """An event for the pitch view: positions turned to the home team's direction (home attacks right)."""
    flip = (lambda p: p) if e["side"] == "home" else (lambda p: [100 - p[0], 100 - p[1]])
    return {"id": e["id"], "clock": stats.clock(e), "period": e["period"], "side": e["side"], "team": e["team"],
            "player": e["player"], "type": e["type"], "outcome": e["outcome"],
            "start": flip(e["start"]), "end": flip(e["end"]) if e["end"] else None,
            "line": playbyplay.line(e, language)}


def _live_stats(so_far, info):
    state = stats.match_state(so_far, info)
    return {k: state[k] for k in ("clock", "score", "expected_goals", "territory", "territory_last_10_min",
                                  "passing", "control_last_10_min", "rhythm_last_10_min")}


async def _live(request, match_id, viewer, speed, start_after, countdown=0):
    match = _load(match_id)
    events, info = match["events"], match["match"]
    global live_matches
    saved = _saved_cards(match_id, viewer)
    source = "saved"
    if saved is None and live_matches >= MAX_LIVE_MATCHES:
        saved, source = _nearest_saved(match_id, viewer), "saved (live agents busy)"
    if saved is None:
        source = "live"
    moments = scout(events, info) + [recap_moment(events, info)]
    cards_at = {}
    for card in saved or []:
        cards_at.setdefault(card["event_id"], []).append(card)
    pending, by_key = {}, {}
    for moment in moments:
        pending.setdefault(moment["event_id"], []).append(moment)
        by_key[(moment["event_id"], moment["kind"])] = moment
    key_ids = {m["event_id"] for m in moments if m["kind"] in EVENT_KINDS}

    def who(card):
        """Who and what a card is about, for the timeline (saved runs don't store it)."""
        m = by_key.get((card["event_id"], card["kind"]), {})
        return {**card, "player": m.get("player"), "team": m.get("team"),
                "final": bool(m.get("facts", {}).get("final_whistle"))}

    yield _sse("start", {"viewer": viewer, "source": source, "countdown": countdown,
                         "teams": {s: info[s]["name"] for s in ("home", "away")}})
    await asyncio.sleep(countdown)          # the page counts down 3, 2, 1; kick-off lands on "Kick-off!"
    agents, tools, out = None, None, asyncio.Queue()
    if saved is None:
        from matchmind.agents import build_agents, match_tools
        live_matches += 1
        tools = match_tools()
        await tools.__aenter__()
        agents = build_agents(tools=tools)

    async def write(moment):
        from matchmind.agents import write_card
        mode = "recap" if moment["kind"] == "recap" else viewer["role"]
        card = await write_card(agents, match_id, viewer_facts(moment, events, info, viewer["player"]), mode, viewer)
        await out.put(_sse("card", who(card)))

    tasks = []
    try:
        seen, current_pace = [], None
        async for e, pace in highlights(events, key_ids, speed=speed, start_after=start_after):
            if await request.is_disconnected():
                return                     # the viewer left: stop, free the live slot
            seen.append(e)
            if pace != current_pace:
                current_pace = pace
                yield _sse("pace", {"pace": pace})
            yield _sse("event", _pitch_event(e, viewer["language"]))
            if len(seen) % STATS_EVERY == 0 or e["type"] in ("shot", "own_goal"):
                yield _sse("stats", _live_stats(stats.events_until(events, e["id"]), info))
            if saved is not None:
                for card in cards_at.get(e["id"], []):
                    yield _sse("card", who(card))
            else:
                new = [asyncio.create_task(write(m)) for m in pending.get(e["id"], []) if m["kind"] != "recap"]
                tasks += new
                if new:                    # hold play at the moment until its commentary is ready
                    await asyncio.wait(new, timeout=CARD_WAIT_S)
                tasks += [asyncio.create_task(write(m)) for m in pending.get(e["id"], []) if m["kind"] == "recap"]
            while not out.empty():
                yield out.get_nowait()
        for task in asyncio.as_completed(tasks):
            await task
            while not out.empty():
                yield out.get_nowait()
        yield _sse("end", {"score": {info[s]["name"]: n for s, n in stats.score(events).items()}})
    finally:
        for task in tasks:
            task.cancel()
        if tools is not None:
            live_matches -= 1
            await tools.__aexit__(None, None, None)

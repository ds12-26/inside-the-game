"""
Tests for the web API, using the saved demo runs (no Azure needed).
"""

import json

from fastapi.testclient import TestClient

from matchmind.render.api import app
from matchmind.ingest.data import load_match

client = TestClient(app)


def sse(text):
    """Parse a Server-Sent Events body into (event, data) pairs."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_page_and_match_info_never_give_away_the_result():
    assert client.get("/").status_code == 200
    info = client.get("/api/match/match_002").json()
    assert info["teams"]["home"]["name"] == "Red Lions" and "final_score" not in json.dumps(info)


def test_live_stream_replays_the_match_with_cards_for_this_viewer():
    params = {"role": "fan", "language": "es", "club": "Blue Sharks", "player": "Moss", "focus": "true", "speed": 1e9}
    messages = sse(client.get("/api/live/match_002", params=params).text)
    kinds = [kind for kind, _ in messages]
    assert kinds[0] == "start" and messages[0][1]["source"] == "saved" and kinds[-1] == "end"
    assert kinds.count("event") == 1609
    cards = [data for kind, data in messages if kind == "card"]
    assert cards and all(c["language"] == "es" for c in cards)
    events = [data for kind, data in messages if kind == "event"]
    raw = {e["id"]: e for e in load_match("match_002")["events"]}
    away = next(e for e in events if e["side"] == "away" and e["end"])
    x, y = raw[away["id"]]["start"]
    assert away["start"] == [100 - x, 100 - y]                         # turned to the home team's direction
    assert messages[-1][1]["score"] == {"Red Lions": 3, "Blue Sharks": 2}


def test_cards_never_arrive_before_their_moment():
    messages = sse(client.get("/api/live/match_002", params={"role": "analyst", "speed": 1e9}).text)
    seen = 0
    for kind, data in messages:
        if kind == "event":
            seen = data["id"]
        if kind == "card":
            assert data["event_id"] <= seen


def test_busy_fallback_never_switches_language(monkeypatch):
    from matchmind.render import api
    monkeypatch.setattr(api, "live_matches", api.MAX_LIVE_MATCHES)      # pretend live agents are busy
    params = {"role": "fan", "language": "hi", "club": "Blue Sharks", "speed": 1e9}
    messages = sse(client.get("/api/live/match_002", params=params).text)
    assert messages[0][1]["source"] == "saved (live agents busy)"
    assert all(data["language"] == "hi" for kind, data in messages if kind == "card")


def test_countdown_holds_kick_off_until_the_page_has_counted_down():
    import time
    start = time.time()
    messages = sse(client.get("/api/live/match_002", params={"role": "analyst", "speed": 1e9, "countdown": 1}).text)
    assert messages[0][1]["countdown"] == 1 and time.time() - start >= 1


def test_live_commentary_arrives_before_play_moves_on(monkeypatch):
    """When agents write live, play waits at each moment so the words match the pitch."""
    import asyncio
    from matchmind import agents

    async def write_card(agents_, match_id, moment, mode, viewer):
        await asyncio.sleep(0.01)                              # the agents take a moment
        return {"event_id": moment["event_id"], "clock": moment["clock"], "kind": moment["kind"], "mode": mode,
                "language": "en", "content": {"text": "line"}, "source": "ai", "fact_check": {}}

    class Tools:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(agents, "write_card", write_card)
    monkeypatch.setattr(agents, "match_tools", lambda: Tools())
    monkeypatch.setattr(agents, "build_agents", lambda tools=None: {})
    messages = sse(client.get("/api/live/match_002", params={"role": "fan", "language": "fr", "speed": 1e9}).text)
    assert messages[0][1]["source"] == "live"
    last_event, late = 0, []
    for kind, data in messages:
        if kind == "event":
            last_event = data["id"]
        if kind == "card" and data["kind"] != "recap" and data["event_id"] != last_event:
            late.append(data["clock"])
    assert late == []

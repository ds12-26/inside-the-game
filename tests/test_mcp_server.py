"""
Tests for the Match Data MCP server, called in-process through a real MCP client.
"""

import asyncio
import json

from mcp import Client

from matchmind.mcp_server import server


def call(tool, **arguments):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)
    return asyncio.run(run())


def result(tool, **arguments):
    return json.loads(call(tool, **arguments).content[0].text)


def test_all_tools_are_listed():
    async def names():
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}
    assert {"match_state", "pass_quality", "territory", "expected_goals", "player_story"} <= asyncio.run(names())


def test_match_state_only_includes_events_so_far():
    state = result("match_state", match_id="match_002", at_event=351)
    assert state["at_event"] == 351
    assert state["score"] == {"Red Lions": 0, "Blue Sharks": 0}


def test_overview_never_gives_away_the_result():
    overview = call("match_overview", match_id="match_002").content[0].text
    assert "final_score" not in overview and "Fox" in overview


def test_unknown_player_error_lists_the_real_players():
    reply = call("player_story", match_id="match_002", player="Messi")
    assert reply.is_error
    assert "Messi" in reply.content[0].text and "Fox" in reply.content[0].text


def test_pass_quality_for_one_player():
    fox = result("pass_quality", match_id="match_002", player="Fox")
    assert fox["attempted"] == 120 and fox["accuracy_pct"] == 88

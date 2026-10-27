"""
Match Data MCP server: gives agents the match events and computed statistics as tools.

Agents never compute or remember numbers themselves; they ask this server. Every
tool takes `at_event`, the ID of the latest event seen, so during live play an
agent only sees what has happened so far (no spoilers), and the server keeps no
state between calls.

Usage:
    python -m matchmind.mcp_server                 # Streamable HTTP on :8001/mcp
    python -m matchmind.mcp_server --stdio
"""

import argparse
from functools import lru_cache

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from matchmind import data, stats

server = MCPServer(
    name="match-data",
    instructions=(
        "Synthetic football match data and statistics. Pass at_event (the latest event ID "
        "you have seen) so answers only include what has happened so far."
    ),
)


@lru_cache(maxsize=8)
def _match(match_id):
    return data.load_match(match_id)


def _events(match_id, at_event):
    return stats.events_until(_match(match_id)["events"], at_event)


def _info(match_id):
    return _match(match_id)["match"]


def _check_player(match_id, player):
    squads = data.squads(_info(match_id))
    if player not in squads:
        raise ToolError(f"No player '{player}' in {match_id}. Players: {', '.join(sorted(squads))}")


def _check_team(match_id, team):
    teams = [_info(match_id)[s]["name"] for s in ("home", "away")]
    if team not in teams:
        raise ToolError(f"No team '{team}' in {match_id}. Teams: {', '.join(teams)}")


@server.tool()
def list_matches() -> list[dict]:
    """Every available match: ID, home team and away team."""
    return data.list_matches()


@server.tool()
def match_overview(match_id: str) -> dict:
    """Teams, squads (name, position, notes such as captain) and pitch coordinate system. Never the result."""
    info = _info(match_id)
    return {
        "match_id": match_id,
        "coordinate_system": info["coordinate_system"],
        "teams": {info[s]["name"]: {"side": s, "short": info[s]["short"], "players": info[s]["players"]}
                  for s in ("home", "away")},
    }


@server.tool()
def match_state(match_id: str, at_event: int | None = None, window_minutes: int = 10) -> dict:
    """The match at event `at_event`: clock, score, xG, territory, passing, control vs chaos and rhythm,
    for the whole match so far and for the last `window_minutes`."""
    return stats.match_state(_events(match_id, at_event), _info(match_id), window_minutes)


@server.tool()
def pass_quality(match_id: str, at_event: int | None = None, team: str | None = None,
                 player: str | None = None) -> dict:
    """Pass accuracy, average distance (m), difficulty rating (0-100), hard and progressive passes,
    final-third entries and accuracy under pressure, for a team, a player or everyone."""
    if team:
        _check_team(match_id, team)
    if player:
        _check_player(match_id, player)
    return stats.pass_quality(_events(match_id, at_event), team=team, player=player)


@server.tool()
def territory(match_id: str, at_event: int | None = None, last_minutes: int | None = None) -> dict:
    """Territorial dominance per team: field tilt (share of final-third actions), average line,
    possession (share of passes) and how often they act under pressure. Optionally only the last N minutes."""
    events = stats.last_minutes(_events(match_id, at_event), last_minutes)
    return {
        "territory": stats.territory(events, _info(match_id)),
        "control": stats.control_vs_chaos(events),
        "rhythm": stats.rhythm(events),
    }


@server.tool()
def expected_goals(match_id: str, at_event: int | None = None) -> dict:
    """xG, goals, finishing vs xG, shots, shots on target and big chances per team, plus the best chances."""
    return stats.expected_goals(_events(match_id, at_event), _info(match_id))


@server.tool()
def player_story(match_id: str, player: str, at_event: int | None = None) -> dict:
    """One player's match so far: touches, passing, shots, xG, goals, assists, defending, saves, cards,
    and their moments in order (goals, chances, saves, milestones, long passes, fast shots)."""
    _check_player(match_id, player)
    return stats.player_story(_events(match_id, at_event), _info(match_id), player)


@server.tool()
def recent_events(match_id: str, at_event: int | None = None, count: int = 10) -> list[dict]:
    """The last `count` events up to `at_event`, with the broadcast clock added."""
    events = _events(match_id, at_event)[-min(count, 50):]
    return [{**e, "clock": stats.clock(e)} for e in events]


def main():
    parser = argparse.ArgumentParser(description="Match Data MCP server.")
    parser.add_argument("--stdio", action="store_true", help="talk over stdin/stdout instead of HTTP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.stdio:
        server.run()
    else:
        server.run("streamable-http", host=args.host, port=args.port, stateless_http=True)


if __name__ == "__main__":
    main()

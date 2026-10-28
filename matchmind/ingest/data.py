"""
Read-only access to the synthetic matches in data/matches/.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "matches"


def list_matches():
    """Every match in data/, as short summaries for a match picker."""
    matches = []
    for path in sorted(DATA_DIR.glob("match_*.json")):
        info = json.loads(path.read_text())["match"]
        matches.append({
            "match_id": info["match_id"],
            "home": info["home"]["name"],
            "away": info["away"]["name"],
        })
    return matches


def load_match(match_id):
    """The full match (metadata and events) for one match ID, e.g. "match_002"."""
    return json.loads((DATA_DIR / f"{match_id}.json").read_text())


def squads(match_info):
    """Every player in the match, by name: {"Fox": {"team": "Red Lions", "position": "AM"}}."""
    players = {}
    for side in ("home", "away"):
        team = match_info[side]["name"]
        for player in match_info[side]["players"]:
            players[player["name"]] = {"team": team, "position": player["position"]}
    return players

# Match Mind

Explainable match intelligence from synthetic football events.

## Agents
- **Welcome** (`matchmind/welcome_agent.py`): works out who the viewer is
  (fan, analyst or broadcaster; club, player, language, metric) and picks their experience.

## Match Data MCP server
`matchmind/mcp_server.py` gives agents the events and the statistics below as MCP tools
(`match_state`, `pass_quality`, `territory`, `expected_goals`, `player_story`,
`recent_events`, `match_overview`, `list_matches`). Every tool takes `at_event`, the latest
event seen, so during live play nothing after that moment is visible.

## How every number is calculated
All statistics are computed in plain Python in `matchmind/stats.py`; no model produces a
number. The pitch is treated as 105 x 68 m. Data coordinates run 0-100 from the acting
team's own goal (x) and across the pitch (y).

| Metric | Definition |
|---|---|
| Pass accuracy | Completed passes / attempted passes (intercepted and out count as failed) |
| Pass distance | Straight-line distance from start to end, in metres |
| Pass difficulty (0-100) | Distance (up to 40 pts, maxing at 50 m) + under pressure (25) + forward progress (up to 20, maxing at 30 m) + ending in the box zone, x ≥ 83 (15). Easy < 35 ≤ medium < 60 ≤ hard |
| Progressive pass | Moves the ball at least 10 m towards goal and ends in the opponent's half |
| Final-third entry | Completed pass that starts before and ends inside the attacking third |
| Field tilt | A team's share of all actions taken in the attacking third |
| Average line | Average x of a team's actions, from its own goal (higher = further up the pitch) |
| Possession | A team's share of passes attempted |
| Control vs chaos | Average actions per possession and turnovers (tackles, interceptions) per 10 minutes. Chaotic: ≥ 13 turnovers per 10 min; controlled: ≥ 7.5 actions per possession or < 8 turnovers; otherwise balanced |
| Rhythm | Actions per minute of match time |
| xG | Sum of each shot's expected-goal value (the chance it is scored, given in the data) |
| Finishing vs xG | Goals scored from shots minus xG (own goals excluded). Below zero = fewer goals than the chances deserved |
| Big chance | A shot with xG ≥ 0.3 |
| Ball / shot speed | **Estimate**: distance / time to the next touch, only when that is 1-2 s (for shots, the save). Event times are whole seconds |
| Milestones | A player's 25th, 50th, 75th and 100th completed pass; passes ≥ 40 m; shots ≥ 90 km/h |

Recent-trend versions (territory, control, rhythm) use the last 10 minutes of match time.

Checks in `tests/test_stats.py` hold the numbers to the data itself: the score after every
goal matches the score recorded in the data, shares always add to 100, and one pass is
worked out by hand.

### Notes on the synthetic data
- Passes under pressure succeed exactly as often as other passes, so pressure is shown as
  context but never used as evidence of composure.
- Every dribble is recorded as lost, so no dribble success rate is shown.

## Setup
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env    # add your Azure OpenAI endpoint, key and deployment

## Run
    python -m matchmind.welcome_agent                      # interactive
    python -m matchmind.welcome_agent --no-ai --role fan   # offline
    python -m matchmind.mcp_server                         # MCP server on :8001/mcp
    python -m pytest

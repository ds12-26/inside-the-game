# Inside the Game

**Fact-checked, personalized match intelligence from synthetic football events.**

The same match, told three ways: live TV-style commentary for a fan, the patterns
and evidence for an analyst, and on-air graphics plus director cues for a broadcaster.
Every number is computed by code. Every sentence an agent writes is checked against the
data by another agent before it reaches the screen.

Built for the *Inside the Game* developer hackathon (Microsoft × Premier League).
All data is synthetic.

**Live demo:** _URL added after deployment_ · **Roadmap:** [ROADMAP.md](ROADMAP.md)

## The problem
Scorelines don't explain matches, and one broadcast can't serve everyone. A casual fan
wants the story of their club; an analyst wants to know *why* the game turned; a producer
needs to know what to put on air next. And generated commentary is only useful if you can
trust it: a model that invents a "second goal" or a "final" is worse than no commentary.

## What it does

| Viewer | Experience |
|---|---|
| **Fan** | TV-broadcast screen: animated pitch with player name tags, scoreboard bug, live commentary in their language (English by default; Spanish, French, Portuguese or Hindi) leaning towards their club, their favourite player followed all match, "who's on top" in plain words. xG is never shown as a decimal: a 0.26 chance is "scored about 1 time in 4". |
| **Analyst** | Live numbers (xG, field tilt, possession, pass accuracy and difficulty, progressive passes, control vs chaos, tempo) and "why it matters" cards with 2-4 pieces of evidence each. |
| **Broadcaster** | Lower-third graphics and talking points for every moment, plus **director cues**: *cut to replay*, *stats package*, *player camera*, *show graphic* or *stay live*, with priority and the reason. All cards are timed, machine-readable JSON a graphics system can render. |
| **Everyone, at full time** | Their own recap, plus an **ensemble report**: the Narrator, Analyst and Broadcaster write in parallel and a Coordinator merges the three perspectives. |

Every card has a **✓ Fact-checked** badge; one click shows each draft, what the
Fact-Checker rejected and why, and the rewrite.

## How it works

```
 synthetic events ─► Replay (live stream) ─► Moment Scout (rules: goals, big chances, cards,
                                                 momentum swings, passing drops, check-ins)
                                                           │
 stats engine (pure Python, tested) ◄── Match Data MCP server (8 tools, capped at "now")
                                                           │
 Welcome agent ── routes the viewer ──►  Agent Framework workflow, per moment:
 (fan / analyst / broadcaster,           Writer ─► Fact-Checker ─► card on screen
  club, player, language)                  ▲            │ problems
                                           └── rewrite ─┘ (then a safe template)
                                                           │
 full time:  Narrator ─┐
             Analyst  ─┼─ fan-in ─► Coordinator ─► Fact-Checker ─► ensemble report
             Broadcaster┘ (fan-out, concurrent)
                                                           │
 FastAPI ── Server-Sent Events ──► one web page (welcome, fan, analyst, broadcaster)
```

### Agents
| Agent | Job |
|---|---|
| **Welcome** | Turns quick picks and/or a sentence ("I support Blue Sharks, love Moss, en español") into a checked profile and routes the viewer. Unknown clubs and players are rejected against the real squads and asked again. |
| **Narrator** (fan) | Live TV-style commentary, partisan but fair, plain words, no decimals, at most 35 words. |
| **Analyst** | Headline, why the moment matters (control vs chaos, territory, pressure, finishing vs xG, rhythm), and evidence copied from the stats. |
| **Studio Producer** (broadcaster) | Graphics text, a talking point and a director cue. |
| **Recap** | Full-time story for each viewer type. |
| **Coordinator** | Merges the three full-time perspectives into one report. |
| **Fact-Checker** | Approves or sends back every draft above, using the facts and the MCP tools. |

The **Moment Scout** is deliberately rules, not a model: it is instant, free and never
misses a goal.

### Orchestration patterns
- **Routed:** the Welcome agent decides which specialist workflow serves the viewer.
- **Sequential with a feedback loop:** Writer → Fact-Checker → (one rewrite) → card, built
  with `WorkflowBuilder` and conditional edges.
- **Concurrent (fan-out / fan-in):** three specialists write the full-time story at the same
  time; a Coordinator merges them and the Fact-Checker verifies the merge.

### Why you can trust it
- **Code computes every number** ([matchmind/stats.py](matchmind/stats.py)); agents only
  write words around facts. Definitions are below.
- **No spoilers, enforced in code:** a function middleware caps every MCP tool call at the
  current moment, whatever the agent asks for.
- **Two layers of checking:** code catches a score the match never had, decimals or jargon
  shown to fans, text in the wrong script for the viewer's language (Devanagari is allowed only
  for Hindi viewers, and Hindi viewers must actually get Hindi); then the Fact-Checker agent checks every claim
  (who did what, chance quality, "again"/"first", invented context such as a crowd or a
  final, calling a goal "the winner" before full time).
- **Always a safe answer:** if a draft fails twice or the model is down, a plain line built
  from the data is shown instead.

Real catches from the demo runs: the Narrator called 105+1' "half-time" while play was on;
an analyst card claimed 85% field tilt when it was 67%; a 1-in-3 chance was called
"clarísima" (very clear); a broadcaster headline called a 95th-minute goal "the winner"
before the 105th-minute equaliser.

## Microsoft technologies

| Technology | How it is used |
|---|---|
| **Microsoft Agent Framework** | All agents (`Agent`), the per-moment workflow and the fan-out/fan-in ensemble (`WorkflowBuilder`, `Executor`), the no-spoilers function middleware, MCP tools (`MCPStdioTool`, `MCPStreamableHTTPTool`). |
| **Model Context Protocol** | [matchmind/mcp_server.py](matchmind/mcp_server.py): the Match Data MCP server exposing events and statistics as tools; runs as its own internal container app. |
| **Microsoft Foundry** | The agents run on a model deployed in a Foundry project (`FoundryChatClient`), authenticated with Azure CLI locally and managed identity in Azure. |
| **Azure OpenAI** | The Welcome agent's profile reading. |
| **Azure Container Apps** | Web app (public) and MCP server (internal) from one image built in Azure Container Registry: [deploy/deploy.sh](deploy/deploy.sh). |
| **GitHub Actions** | Runs the test suite on every push. |

## Run it

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env          # Foundry project endpoint and model; Azure OpenAI for the Welcome agent
    az login                      # the agents sign in with your Azure CLI account

    uvicorn matchmind.api:app --port 8000          # the app: http://localhost:8000
    python -m pytest                                # 52 tests, no Azure needed

Demo links (saved runs, instant, no model calls):
- Red Lions fan following Fox (English): `/?role=fan&club=Red+Lions&player=Fox&focus=1`
- Analyst: `/?role=analyst` · Broadcaster: `/?role=broadcaster`
- The same fan in Hindi: `/?role=fan&club=Red+Lions&player=Fox&focus=1&language=hi`
- A Blue Sharks fan following the 40-year-old keeper Moss, in Spanish:
  `/?role=fan&club=Blue+Sharks&player=Moss&focus=1&language=es`

Any other combination is written live by the agents as the match plays.

Other entry points:

    python -m matchmind.commentary --role fan --club "Blue Sharks" --player Moss --focus --language es
    python -m matchmind.ensemble                    # full-time ensemble report
    python -m matchmind.mcp_server                  # MCP server on :8001/mcp
    python -m matchmind.welcome_agent               # Welcome agent in the terminal
    deploy/deploy.sh                                # deploy to Azure Container Apps

## Project layout

| Path | What |
|---|---|
| `matchmind/stats.py` | Every statistic, from the events seen so far |
| `matchmind/moments.py` | Moment Scout rules and the facts each moment carries |
| `matchmind/agents.py` | Agents, prompts, the writer → Fact-Checker workflow, code checks |
| `matchmind/ensemble.py` | Full-time fan-out / fan-in ensemble report |
| `matchmind/mcp_server.py` | Match Data MCP server |
| `matchmind/welcome_agent.py`, `profile.py` | Welcome agent and the viewer profile |
| `matchmind/playbyplay.py` | Instant play-by-play lines in English, Spanish, French, Portuguese and Hindi |
| `matchmind/replay.py`, `api.py` | Live replay and the web API (Server-Sent Events) |
| `web/` | The single-page app |
| `runs/` | Saved demo runs: every card with its fact-check history |
| `tests/` | 52 tests: stats against the data, agents with fake models, MCP, API |

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
| Passing drop | A team's pass accuracy over the last 5 minutes at least 15 points below its match so far (at least 8 passes) |
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
- The data records no player genders, so agents are told to use names, not pronouns.

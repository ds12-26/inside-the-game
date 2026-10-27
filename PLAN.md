# Build plan (6 hours)

Inside the Game hackathon: explainable match intelligence from synthetic football events.

## Principle
Code computes every number; agents only write words around facts, and a
Fact-Checker agent verifies every claim against the data before it reaches the screen.

## Architecture

```
match_002.json ──► Replay engine (live stream, speed-up)
                        │
                        ▼
            Match Data MCP server  ◄── stats engine (pure Python, tested)
            tools: match_state, player_stats, pass_quality,
                   pressure_trend, possession_flow, recent_events
                        │  (agents call tools via MCP)
                        ▼
   Agent Framework workflow, on each candidate moment:
   Moment Scout ─► Explainer ─► Fact-Checker ──(rejects)──► Explainer
                                     │ approved
                                     ▼
                            Producer (per profile: role, club,
                            player focus, language, metric)
                                     │
   Welcome agent (existing) ─────────┘ supplies profiles
                                     ▼
          FastAPI: SSE stream of timed overlay cards, /welcome, /recap
                                     ▼
          Web page: match clock, overlay cards, profile switcher, audio
   Recap agent: full-time recap per profile, score-checked
```

## Hero technologies

| Technology | Use |
|---|---|
| Microsoft Agent Framework | Agents and the workflow that runs them |
| Azure MCP | Match Data MCP server exposing events and stats as tools |
| Microsoft Foundry project | Model deployment and tracing |
| Azure Container Apps | Hosting the API and MCP server |
| Azure AI Speech | Stretch: spoken commentary for key moments |
| GitHub Copilot Agent Mode | Used for real on part of the build (frontend or tests) |
| Fabric, Cosmos DB, AKS | Roadmap only (see ROADMAP.md) |

## Phases

| # | Time | Phase | Done when |
|---|---|---|---|
| 0 | 0:00–0:20 | Repo, CI, Foundry model, packages | CI green; a test agent replies through Foundry |
| 1 | 0:20–1:35 | Stats engine, replay, MCP server, tests | An MCP client gets correct "match state at minute 60" |
| 2 | 1:35–3:20 | Moment Scout, Explainer, Fact-Checker, Producer, Recap | One command prints checked cards for a Spanish fan and an English analyst |
| 3 | 3:20–4:20 | FastAPI + web page | The same moment shows as two different cards side by side |
| 4 | 4:20–5:00 | Deploy to Azure Container Apps | A public URL works |
| 5 | 5:00–5:20 | Stretch: Azure AI Speech | Key moments play as audio |
| 6 | 5:20–6:00 | README, ROADMAP, demo video | Submitted |

Cut order if late: Speech → Copilot share (Claude builds the frontend) → one container app instead of two → deployment (demo locally).

## Risks
- Agent Framework API changes: 30-minute limit, then plain handoffs between agents.
- Model delay during live play: AI only on key moments, run in parallel; demo uses a saved run.
- Azure permissions or quota: checked in Phase 0.

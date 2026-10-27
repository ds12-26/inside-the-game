# Match Mind

Explainable match intelligence from synthetic football events.

## Agents
- **Welcome** (`matchmind/welcome_agent.py`): works out who the viewer is
  (fan, analyst or broadcaster; club, player, language, metric) and picks their experience.

## Setup
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env    # add your Azure OpenAI endpoint, key and deployment

## Run
    python -m matchmind.welcome_agent                      # interactive
    python -m matchmind.welcome_agent --no-ai --role fan   # offline
    python -m pytest

"""
The agents: writers (Narrator, Analyst, Studio Producer, Recap), the Fact-Checker,
the full-time Coordinator, and the code checks that run before the Fact-Checker.

    prompts.py    what each agent returns, is told and is sent
    checks.py     mistakes caught in code, before any model
    workflow.py   model, MCP tools, no-spoilers guard, writer -> Fact-Checker loop, fallback cards
    ensemble.py   full-time fan-out / fan-in report
    commentary.py runs a whole match for one viewer (saved demo runs)
"""

from matchmind.agents.checks import (completed_pass_problems, devanagari_share, draft_text, own_net_problems,
                                     rule_problems, wrong_language)
from matchmind.agents.prompts import (CHECKER_INSTRUCTIONS, INSTRUCTIONS, SCHEMAS, WRITING_LANGUAGES, Recap,
                                      Verdict, blocking, checker_prompt, match_status, viewer_text, writer_prompt)
from matchmind.agents.workflow import (MAX_ATTEMPTS, MAX_RECAP_ATTEMPTS, Job, build_agents, chat_client,
                                       current_event, fallback_recap, match_tools, no_spoilers, write_card)

__all__ = [
    "blocking",
    "build_agents",
    "chat_client",
    "CHECKER_INSTRUCTIONS",
    "checker_prompt",
    "completed_pass_problems",
    "current_event",
    "devanagari_share",
    "draft_text",
    "fallback_recap",
    "INSTRUCTIONS",
    "Job",
    "match_status",
    "match_tools",
    "MAX_ATTEMPTS",
    "MAX_RECAP_ATTEMPTS",
    "no_spoilers",
    "own_net_problems",
    "Recap",
    "rule_problems",
    "SCHEMAS",
    "Verdict",
    "viewer_text",
    "write_card",
    "writer_prompt",
    "WRITING_LANGUAGES",
    "wrong_language",
]

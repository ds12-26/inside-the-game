"""
Checks done in code before the Fact-Checker agent: mistakes any reader would spot,
found without a model (wrong scores, jargon for fans, wrong language or script,
an own goal in the wrong net, attempted passes called completed, ...).
"""

import re
import unicodedata

from matchmind.agents.guards import check_script, scorelines
from matchmind.agents.prompts import WRITING_LANGUAGES

FAN_MAX_WORDS = 45


# ---------- checks done in code before the Fact-Checker agent ----------


def draft_text(draft, skip=()):
    """All the words in a draft, whatever its shape; separate fields never run together."""
    parts = []
    for key, value in draft.items():
        if key in skip:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            parts.append(draft_text(value))
        elif isinstance(value, list):
            parts += [v if isinstance(v, str) else draft_text(v) for v in value]
    return " | ".join(parts)


# Common short words, to tell Spanish, French and Portuguese text from English.
STOPWORDS = {
    "es": {"el", "los", "las", "del", "que", "con", "para", "por", "en", "un", "una", "y", "es"},
    "fr": {"le", "les", "des", "du", "que", "avec", "pour", "est", "et", "un", "une", "dans", "sur"},
    "pt": {"o", "os", "do", "da", "que", "com", "para", "por", "em", "um", "uma", "e", "no", "na"},
}


def wrong_language(text, language):
    """True if the text reads as English rather than the viewer's language."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    english = sum(w in {"the", "and", "with", "for", "is", "are", "has", "have", "on", "of", "to", "in"} for w in words)
    target = sum(w in STOPWORDS[language] for w in words)
    return english >= 3 and english > target


def completed_pass_problems(text, facts):
    """'838 passes completed' when 838 were attempted: the number completed must match the data."""
    passing = facts.get("passing") or {}
    completed = {v["completed"] for v in passing.values()}
    if not completed:
        return []
    claims = re.findall(r"(\d+)\s+(?:passes\s+completed|completed\s+passes)|complet\w*\s+(\d+)\s+(?:of\s+\d+\s+)?passes", text, re.IGNORECASE)
    wrong = sorted({int(a or b) for a, b in claims} - completed)
    return [f"FALSE: {n} passes were not completed; completed passes were {sorted(completed)}" for n in wrong]


def own_net_problems(text, facts):
    """An own goal said to go into the wrong team's net ("into Red Lions' own net")."""
    own_goals = [g for g in facts.get("goals", []) if g.get("own_goal")]
    if facts.get("own_goal"):
        own_goals.append({"team": facts["own_goal"]["goal_counts_for"]})
    return [f"FALSE: the own goal went into the other team's net, not {g['team']}'s"
            for g in own_goals if re.search(re.escape(g["team"]) + r"[’']?s?\s+(?:own\s+)?net", text)]


def devanagari_share(text):
    """Share of words in Devanagari, skipping names (capitalised Latin words) and numbers."""
    words = [w for w in re.findall(r"\w+", text) if not w.isdigit() and not (w[0].isupper() and w.isascii())]
    hindi = sum(any("DEVANAGARI" in unicodedata.name(c, "") for c in w) for w in words)
    return hindi / len(words) if words else 1


def rule_problems(job):
    """Problems any reader would spot, found without a model."""
    text, problems = draft_text(job.draft), []
    try:
        check_script(text, job.viewer.get("language", "en"))
    except ValueError as error:
        problems.append(str(error))
    facts = job.moment["facts"]
    real = [sorted(map(int, s.split("-"))) for s in facts["scores_so_far"]]
    for pair in scorelines(text):
        if sorted(pair) not in real:
            problems.append(f"mentions the score {pair[0]}-{pair[1]}, which this match has not had; "
                            f"it is {'-'.join(map(str, facts['score'].values()))}")
    for_fan = job.mode == "fan" or (job.mode == "recap" and job.viewer.get("role", "fan") == "fan")
    prose = draft_text(job.draft, skip=("evidence",))      # evidence chips are label/value pairs
    problems += own_net_problems(prose, job.moment["facts"])
    problems += completed_pass_problems(prose, job.moment["facts"])
    if not for_fan and re.search(r"\b\d{1,3}\s+(?:possession|field tilt|pass accuracy|accuracy)\b", prose, re.IGNORECASE):
        problems.append("write percentages with the % sign, e.g. 69% possession")
    if re.search(r"\d\s*%\s*(?:of\s+)?(?:the\s+)?xG|xG\s+(?:of\s+)?\d+\s*%", text, re.IGNORECASE):
        problems.append("FALSE: xG is not a percentage (e.g. 0.81 xG, not 81% xG)")
    language = job.viewer.get("language", "en")
    if language == "en" and re.search(r"\b(he|his|him|himself|she|her|hers|herself)\b", prose, re.IGNORECASE):
        problems.append("refer to players by name, not he/his/she/her: the data doesn't record genders")
    if language in STOPWORDS and wrong_language(prose, language):
        problems.append(f"write in {WRITING_LANGUAGES[language]}, not English")
    if job.viewer.get("language") == "hi" and devanagari_share(text) < 0.5:
        problems.append("the viewer chose Hindi: write in Hindi (Devanagari), keeping only names in Latin letters")
    if job.mode == "fan" or (job.mode == "recap" and job.viewer.get("role", "fan") == "fan"):
        if re.search(r"\d[.,]\d", text):
            problems.append("fans should not see decimals; describe the chance in words")
        if re.search(r"\bxG\b", text, re.IGNORECASE):
            problems.append("fans should not see the term xG; describe the chance in words")
        if re.search(r"\d\s*%|field tilt", text, re.IGNORECASE):
            problems.append("fans should not see percentages or analyst terms; say it in plain words")
        if job.mode == "fan" and len(text.split()) > FAN_MAX_WORDS:
            problems.append(f"too long to read aloud: keep it under {FAN_MAX_WORDS} words")
    return problems

"""
Shared safety checks for text written by the model.
"""

import re
import unicodedata


# Scripts each language may use. Latin is always allowed: team and player names are Latin.
SCRIPTS = {"hi": ("LATIN", "DEVANAGARI")}


def check_latin_text(text):
    """Raise if the text contains letters from a non-Latin script.

    Models occasionally slip a word from another language into English output
    (e.g. a Devanagari fragment inside "decisive"). Accented Latin letters such
    as é or ñ are fine.
    """
    check_script(text, "en")


def check_script(text, language):
    """Raise if the text contains letters from a script the viewer's language doesn't use."""
    allowed = SCRIPTS.get(language, ("LATIN",))
    for char in text:
        if char.isalpha() and not unicodedata.name(char, "").startswith(allowed):
            raise ValueError(f"unexpected character '{char}' for language '{language}'")


# "3-2" or "3–2", but not "11-pass", and not a stat like "27-15 on shots".
_PAIR = re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b(?!\s*-?\s*pass)")
_STAT_WORDS = re.compile(
    r"^\W*(?:(?:edge|advantage|margin|split|count|tally)\s+)?(?:(?:on|in|for)\s+)?(?:the\s+)?(?:shots?|passes|passing|saves?|corners?|fouls?|tackles?|"
    r"chances?|attempts?|possession|xg|touches|on target|ball wins?)\b",
    re.IGNORECASE,
)
MAX_GOALS = 9  # a pair with a bigger number is a statistic, not a score


def scorelines(text):
    """Every pair of numbers in the text that reads as a football score."""
    found = []
    for match in _PAIR.finditer(text):
        a, b = int(match.group(1)), int(match.group(2))
        if a > MAX_GOALS or b > MAX_GOALS:
            continue
        if _STAT_WORDS.match(text[match.end():]):
            continue
        found.append((a, b))
    return found

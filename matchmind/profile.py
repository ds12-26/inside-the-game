"""
The viewer profile: who is watching and what they want from the match.

The Welcome agent builds it; every later stage (commentary, analysis,
overlays, recaps) reads it to shape what that viewer sees.
"""

from dataclasses import asdict, dataclass

ROLES = {
    "fan": "Story-led live view of the match, about your club and players",
    "analyst": "Data-heavy view: patterns, pressure, pass quality, evidence for every claim",
    "broadcaster": "Studio view: timed overlay feed, talking points, ready-to-air recaps",
}

# Where each role is taken next.
EXPERIENCES = {"fan": "fan_live", "analyst": "analyst_desk", "broadcaster": "studio"}

# How much detail each role gets by default.
DEPTHS = {"fan": "casual", "analyst": "detailed", "broadcaster": "studio"}

# Latin-script languages only for now, so the Latin-text guard still applies.
LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French", "pt": "Portuguese"}

# Metrics a viewer can choose to follow; each can be computed from the event data.
METRICS = {
    "pass_accuracy": "Pass accuracy",
    "xg": "Expected goals (xG)",
    "shots": "Shots",
    "tackles": "Tackles won",
    "interceptions": "Interceptions",
    "dribbles": "Dribbles",
    "saves": "Saves",
    "possession": "Possession",
}


@dataclass
class Profile:
    role: str | None = None            # fan, analyst or broadcaster
    club: str | None = None            # favorite club (a team in the match), None = neutral
    player: str | None = None          # favorite player (a player in the match)
    player_focus: bool = False         # follow that player throughout the match
    language: str = "en"
    focus_metric: str | None = None    # a single metric the viewer cares about
    depth: str | None = None           # casual, detailed or studio

    @property
    def experience(self):
        return EXPERIENCES.get(self.role)

    def to_dict(self):
        return {**asdict(self), "experience": self.experience}

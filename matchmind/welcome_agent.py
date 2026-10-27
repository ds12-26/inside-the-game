"""
Welcome agent: works out who the viewer is and takes them to their experience.

A viewer can tap quick picks (role, club, player, language, metric), type a
sentence about themselves, or both. The agent turns that into a Profile:

    "I support Blue Sharks, love watching Moss, prefer Spanish"
        -> fan, club Blue Sharks, player Moss, language es -> fan_live

Rules:
  - quick picks always win over what the model read from the free text
  - every club and player is checked against the real squads; unknown names
    are dropped and the viewer is asked again, with the valid options
  - the greeting never gives away the result (no spoilers)
  - without the model (offline, or if it fails) a keyword reader and template
    greetings are used, so taps alone always produce a valid profile

Usage:
    python -m matchmind.welcome_agent                         # interactive
    python -m matchmind.welcome_agent --text "analyst, I care about xG"
    python -m matchmind.welcome_agent --no-ai --role fan      # free, offline
"""

import argparse
import json
import re

from matchmind.guards import check_script, scorelines
from matchmind.data import load_match, squads
from matchmind.profile import DEPTHS, LANGUAGES, METRICS, ROLES, Profile

SYSTEM_PROMPT = """You are the Welcome agent in a football match intelligence app.
A viewer has told you about themselves. Work out their profile, then greet them.

Rules:
- Use ONLY the teams and players listed. If the viewer names a club or player that
  is not listed, return the name exactly as they wrote it; it will be checked.
- role is "fan", "analyst" or "broadcaster", or null if you cannot tell.
- language is the language the viewer asks for, or the one they write in.
- player_focus is true only if they want to follow one player throughout the match.
- focus_metric is one of the listed metrics, or null.
- Values in "already_chosen" are fixed: keep them.
- greeting: one or two warm sentences in the viewer's language. Never mention the
  score, the result or any numbers; the viewer has not watched the match yet.

Reply with JSON:
{
  "role": "fan",
  "club": "Blue Sharks",
  "player": "Moss",
  "player_focus": false,
  "language": "es",
  "focus_metric": null,
  "greeting": "..."
}"""

# Templates for greetings and follow-up questions, in every supported language.
TEXT = {
    "en": {
        "start": "Welcome! Tell us who you are: fan, analyst or broadcaster.",
        "fan": "Welcome! Your fan view is ready.",
        "analyst": "Welcome! Your analyst desk is ready.",
        "broadcaster": "Welcome! Your studio view is ready.",
        "club": "We'll follow the match through {club}'s eyes.",
        "player": "{player} stays in focus throughout the match.",
        "ask_role": "Are you a fan, an analyst or a broadcaster?",
        "ask_club": "Which club do you support? (or stay neutral)",
        "ask_metric": "Is there one metric you want to follow?",
        "unknown_club": "We couldn't find \"{value}\" in this match. Which club do you mean?",
        "unknown_player": "We couldn't find \"{value}\" in this match. Which player do you mean?",
    },
    "es": {
        "start": "¡Bienvenido! Cuéntanos quién eres: aficionado, analista o profesional de medios.",
        "fan": "¡Bienvenido! Tu vista de aficionado está lista.",
        "analyst": "¡Bienvenido! Tu mesa de análisis está lista.",
        "broadcaster": "¡Bienvenido! Tu vista de estudio está lista.",
        "club": "Seguiremos el partido desde el lado de {club}.",
        "player": "{player} estará en foco durante todo el partido.",
        "ask_role": "¿Eres aficionado, analista o profesional de medios?",
        "ask_club": "¿De qué club eres? (o sigue neutral)",
        "ask_metric": "¿Hay alguna estadística que quieras seguir?",
        "unknown_club": "No encontramos \"{value}\" en este partido. ¿Qué club quieres decir?",
        "unknown_player": "No encontramos \"{value}\" en este partido. ¿Qué jugador quieres decir?",
    },
    "fr": {
        "start": "Bienvenue ! Dites-nous qui vous êtes : supporter, analyste ou diffuseur.",
        "fan": "Bienvenue ! Votre vue supporter est prête.",
        "analyst": "Bienvenue ! Votre poste d'analyse est prêt.",
        "broadcaster": "Bienvenue ! Votre vue studio est prête.",
        "club": "Nous suivrons le match du point de vue de {club}.",
        "player": "{player} sera suivi tout au long du match.",
        "ask_role": "Êtes-vous supporter, analyste ou diffuseur ?",
        "ask_club": "Quel club soutenez-vous ? (ou restez neutre)",
        "ask_metric": "Y a-t-il une statistique que vous voulez suivre ?",
        "unknown_club": "Nous n'avons pas trouvé « {value} » dans ce match. Quel club voulez-vous dire ?",
        "unknown_player": "Nous n'avons pas trouvé « {value} » dans ce match. Quel joueur voulez-vous dire ?",
    },
    "pt": {
        "start": "Bem-vindo! Conte-nos quem você é: torcedor, analista ou profissional de transmissão.",
        "fan": "Bem-vindo! Sua visão de torcedor está pronta.",
        "analyst": "Bem-vindo! Sua mesa de análise está pronta.",
        "broadcaster": "Bem-vindo! Sua visão de estúdio está pronta.",
        "club": "Vamos acompanhar a partida pelo lado do {club}.",
        "player": "{player} estará em destaque durante toda a partida.",
        "ask_role": "Você é torcedor, analista ou profissional de transmissão?",
        "ask_club": "Para qual clube você torce? (ou fique neutro)",
        "ask_metric": "Há alguma estatística que você queira acompanhar?",
        "unknown_club": "Não encontramos \"{value}\" nesta partida. Qual clube você quer dizer?",
        "unknown_player": "Não encontramos \"{value}\" nesta partida. Qual jogador você quer dizer?",
    },
    "hi": {
        "start": "स्वागत है! बताइए आप कौन हैं: फ़ैन, विश्लेषक या ब्रॉडकास्टर।",
        "fan": "स्वागत है! आपका फ़ैन व्यू तैयार है।",
        "analyst": "स्वागत है! आपकी एनालिस्ट डेस्क तैयार है।",
        "broadcaster": "स्वागत है! आपका स्टूडियो व्यू तैयार है।",
        "club": "हम मैच को {club} की नज़र से देखेंगे।",
        "player": "{player} पूरे मैच में फ़ोकस में रहेंगे।",
        "ask_role": "क्या आप फ़ैन हैं, विश्लेषक या ब्रॉडकास्टर?",
        "ask_club": "आप किस क्लब को सपोर्ट करते हैं? (या न्यूट्रल रहें)",
        "ask_metric": "क्या कोई एक आँकड़ा है जिसे आप फ़ॉलो करना चाहते हैं?",
        "unknown_club": "इस मैच में \"{value}\" नहीं मिला। आपका मतलब कौन-सा क्लब है?",
        "unknown_player": "इस मैच में \"{value}\" नहीं मिला। आपका मतलब कौन-सा खिलाड़ी है?",
    },
}

# Answers that mean "none, thanks" for the optional choices.
NONE_ANSWERS = {"", "none", "neutral", "no", "skip", "null"}

# Keywords the offline reader looks for in free text.
ROLE_WORDS = {
    "broadcaster": ["broadcast", "presenter", "producer", "studio", "commentator", "journalist", "media"],
    "analyst": ["analyst", "analysis", "data", "stats", "tactic", "scout", "coach"],
    "fan": ["fan", "support", "aficionado", "supporter", "torcedor", "hincha", "फ़ैन", "फैन", "समर्थक"],
}
LANGUAGE_WORDS = {
    "en": ["english", "inglés", "anglais", "inglês"],
    "es": ["spanish", "español", "espanol", "espagnol", "espanhol"],
    "fr": ["french", "français", "francais", "francés", "francês"],
    "pt": ["portuguese", "português", "portugues", "portugués", "portugais"],
    "hi": ["hindi", "हिंदी", "हिन्दी"],
}
METRIC_WORDS = {
    "xg": ["xg", "expected goals"],
    "pass_accuracy": ["pass"],
    "shots": ["shot"],
    "tackles": ["tackl"],
    "interceptions": ["intercept"],
    "dribbles": ["dribbl"],
    "saves": ["save"],
    "possession": ["possession"],
}
FOCUS_WORDS = ["follow", "focus", "track", "only watch", "just watch"]


def teams(match_info):
    return [match_info["home"]["name"], match_info["away"]["name"]]


def find(value, options):
    """The option matching value, ignoring case, or None."""
    wanted = str(value).strip().lower()
    return next((o for o in options if o.lower() == wanted), None)


def find_club(value, match_info):
    """A club by full name ("Red Lions"), short code ("RED") or nickname ("Lions")."""
    for side in ("home", "away"):
        team = match_info[side]
        names = [team["name"], team["short"], team["name"].split()[-1]]
        if find(value, names):
            return team["name"]
    return None


def check_choices(raw, match_info):
    """Keep only valid choices. Returns (choices, rejected names).

    A key present with a "none" answer (e.g. club "neutral") is kept as None,
    so the viewer is not asked about it again.
    """
    choices, rejected = {}, []
    players = squads(match_info)
    for key, value in raw.items():
        if value is None and key not in ("club", "player", "focus_metric"):
            continue
        answered_none = value is None or str(value).strip().lower() in NONE_ANSWERS
        if key == "role" and not answered_none:
            if find(value, ROLES):
                choices["role"] = find(value, ROLES)
        elif key == "club":
            club = None if answered_none else find_club(value, match_info)
            if club or answered_none:
                choices["club"] = club
            else:
                rejected.append({"field": "club", "value": str(value)})
        elif key == "player":
            player = None if answered_none else find(value, players)
            if player or answered_none:
                choices["player"] = player
            else:
                rejected.append({"field": "player", "value": str(value)})
        elif key == "language" and not answered_none:
            code = find(value, LANGUAGES) or find(value, LANGUAGES.values())
            if code in LANGUAGES.values():
                code = next(k for k, v in LANGUAGES.items() if v == code)
            if code:
                choices["language"] = code
        elif key == "focus_metric":
            metric = None if answered_none else find(value, METRICS)
            if metric or answered_none:
                choices["focus_metric"] = metric
        elif key == "player_focus":
            choices["player_focus"] = value is True or str(value).lower() == "true"
        elif key == "depth" and value in DEPTHS.values():
            choices["depth"] = value
    return choices, rejected


def has_word(text, word):
    """True if a word in text starts with `word` ("tactic" finds "tactics")."""
    return re.search(r"\b" + re.escape(word), text) is not None


def has_name(text, name):
    """True if text contains `name` as a whole word ("Fox", but not "Foxes")."""
    return re.search(r"\b" + re.escape(name.lower()) + r"\b", text) is not None


def read_offline(message, match_info):
    """Pick choices out of free text with keywords: no model needed."""
    text = message.lower()
    raw = {}
    for role, words in ROLE_WORDS.items():
        if any(has_word(text, w) for w in words):
            raw["role"] = role
            break
    for side in ("home", "away"):
        team = match_info[side]
        if any(has_name(text, n) for n in (team["name"], team["short"], team["name"].split()[-1])):
            raw["club"] = team["name"]
            break
    for player in squads(match_info):
        if has_name(text, player):
            raw["player"] = player
            break
    for code, words in LANGUAGE_WORDS.items():
        if any(has_word(text, w) for w in words):
            raw["language"] = code
    for metric, words in METRIC_WORDS.items():
        if any(has_word(text, w) for w in words):
            raw["focus_metric"] = metric
            break
    if raw.get("player") and any(w in text for w in FOCUS_WORDS):
        raw["player_focus"] = True
    return raw


def build_profile(choices):
    profile = Profile(**{k: v for k, v in choices.items() if k in Profile.__dataclass_fields__})
    if not profile.player:
        profile.player_focus = False
    if profile.role and not profile.depth:
        profile.depth = DEPTHS[profile.role]
    return profile


def follow_ups(profile, choices, rejected, match_info):
    """The questions still worth asking, with the valid options for each."""
    text = TEXT[profile.language]
    questions = []
    for item in rejected:
        if item["field"] == "club" and not choices.get("club"):
            questions.append({"field": "club", "question": text["unknown_club"].format(value=item["value"]),
                              "options": teams(match_info) + ["neutral"]})
        if item["field"] == "player" and not choices.get("player"):
            questions.append({"field": "player", "question": text["unknown_player"].format(value=item["value"]),
                              "options": sorted(squads(match_info))})
    asked = {q["field"] for q in questions}
    if not profile.role:
        questions.insert(0, {"field": "role", "question": text["ask_role"], "options": list(ROLES)})
    if profile.role == "fan" and "club" not in choices and "club" not in asked:
        questions.append({"field": "club", "question": text["ask_club"], "options": teams(match_info) + ["neutral"]})
    if profile.role == "analyst" and "focus_metric" not in choices:
        questions.append({"field": "focus_metric", "question": text["ask_metric"], "options": list(METRICS) + ["none"]})
    return questions


def template_greeting(profile):
    text = TEXT[profile.language]
    if not profile.role:
        return text["start"]
    parts = [text[profile.role]]
    if profile.club:
        parts.append(text["club"].format(club=profile.club))
    if profile.player_focus:
        parts.append(text["player"].format(player=profile.player))
    return " ".join(parts)


def greeting_problems(greeting, language="en"):
    """Why a model greeting can't be shown, or an empty list."""
    problems = []
    if not isinstance(greeting, str) or not greeting.strip():
        return ["greeting is empty"]
    try:
        check_script(greeting, language)
    except ValueError as error:
        problems.append(str(error))
    if scorelines(greeting) or re.search(r"\d", greeting):
        problems.append("greeting mentions numbers or a score (spoiler)")
    return problems


def welcome(match_info, picks=None, message="", ask=None, use_ai=True):
    """Build a viewer profile from quick picks and/or free text. `ask` can be swapped out in tests.

    Returns the profile, where to take the viewer, a greeting, and any
    follow-up questions still worth asking.
    """
    picks = picks or {}
    from_text, source, fallback_reason, model_greeting = {}, "template", None, None

    if message.strip() and use_ai:
        if ask is None:
            from matchmind.llm import ask_json as ask
        try:
            payload = {
                "message": message,
                "already_chosen": picks,
                "teams": teams(match_info),
                "players": {name: p["team"] for name, p in squads(match_info).items()},
                "roles": list(ROLES),
                "languages": LANGUAGES,
                "metrics": list(METRICS),
            }
            reply = ask(SYSTEM_PROMPT, json.dumps(payload))
            model_greeting = reply.pop("greeting", None)
            from_text = reply
            source = "ai"
        except Exception as error:
            fallback_reason = str(error) or type(error).__name__
    if message.strip() and source == "template":
        from_text = read_offline(message, match_info)

    text_choices, rejected = check_choices(from_text, match_info)
    pick_choices, pick_rejected = check_choices(picks, match_info)
    choices = {**text_choices, **pick_choices}           # quick picks win
    rejected = [r for r in rejected + pick_rejected if r["field"] not in pick_choices]
    profile = build_profile(choices)

    greeting = template_greeting(profile)
    greeting_source = "template"
    if model_greeting is not None and not greeting_problems(model_greeting, profile.language) and not rejected:
        greeting, greeting_source = model_greeting.strip(), "ai"

    result = {
        "profile": profile.to_dict(),
        "ready": profile.role is not None,
        "follow_ups": follow_ups(profile, choices, rejected, match_info),
        "rejected": rejected,
        "greeting": greeting,
        "source": source,
        "greeting_source": greeting_source,
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


# ---------- command line ----------


def ask_follow_ups(questions):
    """Ask each follow-up in the terminal; Enter skips an optional one."""
    answers = {}
    for q in questions:
        reply = input(f"{q['question']}\n  options: {', '.join(q['options'])}\n> ").strip()
        answers[q["field"]] = reply or "none"
    return answers


def main():
    parser = argparse.ArgumentParser(description="Welcome a viewer and build their profile.")
    parser.add_argument("--match", default="match_002")
    parser.add_argument("--text", help="what the viewer says about themselves")
    parser.add_argument("--role", choices=list(ROLES), help="quick pick: role")
    parser.add_argument("--no-ai", action="store_true", help="keywords and templates only: free, offline")
    args = parser.parse_args()

    match_info = load_match(args.match)["match"]
    picks = {"role": args.role} if args.role else {}
    interactive = args.text is None
    message = args.text
    if interactive:
        print(f"\n{match_info['home']['name']} vs {match_info['away']['name']}\n")
        print(TEXT["en"]["start"])
        message = input("Tell us about yourself (club, player, language...), or press Enter:\n> ")

    result = welcome(match_info, picks, message, use_ai=not args.no_ai)
    while interactive and result["follow_ups"]:
        print(f"\n{result['greeting']}")
        # Carry over what is already known; empty values stay open so they can still be asked.
        known = {k: v for k, v in result["profile"].items()
                 if v and k not in ("experience", "depth")}
        picks = {**picks, **known, **ask_follow_ups(result["follow_ups"])}
        result = welcome(match_info, picks, use_ai=not args.no_ai)

    print(f"\n{result['greeting']}\n")
    print(json.dumps(result["profile"], indent=2, ensure_ascii=False))
    if result["ready"]:
        print(f"\nTaking you to: {result['profile']['experience']}")
    else:
        print("\nStill needed:", ", ".join(q["field"] for q in result["follow_ups"]))


if __name__ == "__main__":
    main()

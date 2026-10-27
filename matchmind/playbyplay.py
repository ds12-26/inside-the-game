"""
Instant play-by-play lines, written by code so the screen never waits for a model.

Only events a TV commentator would call out get a line; routine passes in
midfield move the ball on the pitch but stay silent.
"""

from matchmind import stats

LINES = {
    "en": {
        "kick_off": "{team} kick off.",
        "pass_final_third": "{player} plays it into the final third.",
        "pass_long": "Long ball from {player}.",
        "shot_goal": "{player} scores!",
        "shot_saved": "{player} shoots, saved!",
        "shot_off_target": "{player} shoots, wide.",
        "shot_blocked": "{player}'s shot is blocked.",
        "tackle": "Strong tackle from {player}.",
        "interception": "{player} reads it and intercepts.",
        "foul": "Foul by {player} on {fouled}.",
        "card": "Yellow card for {player}.",
        "corner": "Corner for {team}, {player} to take.",
        "cross": "{player} whips in a cross.",
        "own_goal": "Own goal! It goes in off {player}.",
    },
    "es": {
        "kick_off": "{team} pone el balón en juego.",
        "pass_final_third": "{player} la mete en el último tercio.",
        "pass_long": "Balón largo de {player}.",
        "shot_goal": "¡Gol de {player}!",
        "shot_saved": "¡Dispara {player}, y la paran!",
        "shot_off_target": "Dispara {player}, se va fuera.",
        "shot_blocked": "Bloquean el disparo de {player}.",
        "tackle": "Gran entrada de {player}.",
        "interception": "{player} lo lee e intercepta.",
        "foul": "Falta de {player} sobre {fouled}.",
        "card": "Tarjeta amarilla para {player}.",
        "corner": "Córner para {team}, lo saca {player}.",
        "cross": "Centro de {player}.",
        "own_goal": "¡Gol en propia puerta de {player}!",
    },
    "fr": {
        "kick_off": "{team} donne le coup d'envoi.",
        "pass_final_third": "{player} trouve le dernier tiers.",
        "pass_long": "Long ballon de {player}.",
        "shot_goal": "But de {player} !",
        "shot_saved": "Frappe de {player}, arrêtée !",
        "shot_off_target": "Frappe de {player}, à côté.",
        "shot_blocked": "La frappe de {player} est contrée.",
        "tackle": "Beau tacle de {player}.",
        "interception": "{player} lit le jeu et intercepte.",
        "foul": "Faute de {player} sur {fouled}.",
        "card": "Carton jaune pour {player}.",
        "corner": "Corner pour {team}, tiré par {player}.",
        "cross": "Centre de {player}.",
        "own_goal": "But contre son camp de {player} !",
    },
    "pt": {
        "kick_off": "{team} dá a saída.",
        "pass_final_third": "{player} coloca a bola no último terço.",
        "pass_long": "Bola longa de {player}.",
        "shot_goal": "Gol de {player}!",
        "shot_saved": "{player} chuta, defendido!",
        "shot_off_target": "{player} chuta, para fora.",
        "shot_blocked": "O chute de {player} é bloqueado.",
        "tackle": "Ótimo desarme de {player}.",
        "interception": "{player} lê a jogada e intercepta.",
        "foul": "Falta de {player} em {fouled}.",
        "card": "Cartão amarelo para {player}.",
        "corner": "Escanteio para {team}, {player} cobra.",
        "cross": "{player} cruza na área.",
        "own_goal": "Gol contra de {player}!",
    },
    "hi": {
        "kick_off": "{team} ने किक-ऑफ़ किया।",
        "pass_final_third": "{player} ने गेंद आख़िरी तिहाई में पहुँचाई।",
        "pass_long": "{player} का लंबा पास।",
        "shot_goal": "{player} का गोल!",
        "shot_saved": "{player} का शॉट, और बचाव!",
        "shot_off_target": "{player} का शॉट, बाहर।",
        "shot_blocked": "{player} का शॉट ब्लॉक हो गया।",
        "tackle": "{player} का ज़बरदस्त टैकल।",
        "interception": "{player} ने खेल पढ़ा और गेंद छीन ली।",
        "foul": "{player} का {fouled} पर फ़ाउल।",
        "card": "{player} को पीला कार्ड।",
        "corner": "{team} को कॉर्नर, {player} लेंगे।",
        "cross": "{player} का क्रॉस।",
        "own_goal": "आत्मघाती गोल! गेंद {player} से लगकर अंदर।",
    },
}


def line_key(event):
    """Which line an event gets, or None for events that stay silent."""
    kind = event["type"]
    if kind == "pass":
        if event["outcome"] != "complete":
            return None
        if stats.metres(event["start"], event["end"]) >= stats.LONG_PASS_M:
            return "pass_long"
        if event["start"][0] < stats.FINAL_THIRD_X <= event["end"][0]:
            return "pass_final_third"
        return None
    if kind == "shot":
        return f"shot_{event['outcome']}"
    if kind in ("kick_off", "tackle", "interception", "foul", "card", "corner", "cross", "own_goal"):
        return kind
    return None


def line(event, language="en"):
    """The play-by-play line for an event, or None."""
    key = line_key(event)
    if key is None:
        return None
    return LINES[language][key].format(team=event["team"], player=event["player"],
                                       fouled=event.get("fouled_player", ""))

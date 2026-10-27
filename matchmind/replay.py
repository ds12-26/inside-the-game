"""
Replays a synthetic match as a live event stream.

Events arrive in event order, spaced by match time divided by `speed`
(speed 60 = one match minute per real second). Gaps between periods are not
waited out, since match minutes restart or overlap there (45+2' then 45').
"""

import asyncio

from matchmind.stats import seconds


async def stream(events, speed=60, start_after=0):
    """Yield events after event ID `start_after`, as if they were happening live."""
    previous = None
    for event in events:
        if event["id"] <= start_after:
            continue
        if previous is not None and event["period"] == previous["period"]:
            gap = max(0, seconds(event) - seconds(previous))
            await asyncio.sleep(gap / speed)
        previous = event
        yield event


# Highlights pacing: how TV makes a match easy to follow. Quiet play fast-forwards; the
# build-up to each big moment plays close to real time; after it, play pauses for reading.
FAST_RATE = 120        # match seconds per real second while fast-forwarding
SLOW_RATE = 6          # match seconds per real second in the build-up to a big moment
BUILD_UP_S = 40        # match seconds before a big moment that play slows down for
HOLD_S = 4             # real seconds to pause after a big moment


def slow_events(events, key_ids):
    """IDs of events in the build-up to (or at) a big moment, within the same period."""
    slow, next_key = set(), None
    for e in reversed(events):
        if e["id"] in key_ids:
            next_key = e
        if next_key and next_key["period"] == e["period"] and seconds(next_key) - seconds(e) <= BUILD_UP_S:
            slow.add(e["id"])
    return slow


async def highlights(events, key_ids, speed=1.0, start_after=0):
    """Yield (event, pace) like a TV highlights edit; pace is "slow" near big moments, else "fast"."""
    slow = slow_events(events, key_ids)
    previous = None
    for event in events:
        if event["id"] <= start_after:
            continue
        pace = "slow" if event["id"] in slow else "fast"
        if previous is not None and event["period"] == previous["period"]:
            gap = max(0, seconds(event) - seconds(previous))
            await asyncio.sleep(gap / ((SLOW_RATE if pace == "slow" else FAST_RATE) * speed))
        previous = event
        yield event, pace
        if event["id"] in key_ids:
            await asyncio.sleep(HOLD_S / speed)

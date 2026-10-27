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

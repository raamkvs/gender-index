"""Response delay helper for enforcing timing constraints on API responses."""
from __future__ import annotations

import asyncio
import time
from typing import Callable

MIN_RESPONSE_SECONDS = 10
MAX_RESPONSE_SECONDS = 30
POLL_INTERVAL_SECONDS = 1


async def wait_for_response_window(
    *,
    is_ready: Callable[[], bool],
) -> None:
    """
    Block until minimum elapsed time, then poll is_ready() every 1s.
    Return as soon as is_ready() is True (after min), or at max elapsed time.

    Args:
        is_ready: Callable that returns True when ready to respond early.
                  If always False, returns at exactly MIN_RESPONSE_SECONDS.

    Timing:
        - Always waits at least MIN_RESPONSE_SECONDS (10s)
        - After min, checks is_ready() every POLL_INTERVAL_SECONDS (1s)
        - Returns immediately after min if is_ready() is True
        - Otherwise returns at MAX_RESPONSE_SECONDS (30s)
    """
    start_time = time.time()

    # Wait for minimum response time
    await asyncio.sleep(MIN_RESPONSE_SECONDS)

    # After minimum, poll is_ready() until max time
    while time.time() - start_time < MAX_RESPONSE_SECONDS:
        if is_ready():
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # Max time reached
    return

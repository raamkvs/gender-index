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
    wait_until_max: bool = True,
) -> None:
    """
    Block until minimum elapsed time, then optionally poll until max.

    Args:
        is_ready: Returns True when the response can be sent early (after min).
        wait_until_max: If False, return immediately after MIN seconds (analyze).
                        If True, keep polling until is_ready or MAX (status).
    """
    start_time = time.time()

    await asyncio.sleep(MIN_RESPONSE_SECONDS)

    if not wait_until_max:
        return

    while time.time() - start_time < MAX_RESPONSE_SECONDS:
        if is_ready():
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

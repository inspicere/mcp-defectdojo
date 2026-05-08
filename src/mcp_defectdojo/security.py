import asyncio
import time
from collections import defaultdict, deque

from fastmcp.exceptions import ToolError

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10000
MAX_NAME_LENGTH = 200


def validate_field_length(value: str, field_name: str, max_length: int) -> None:
    if len(value) > max_length:
        raise ToolError(
            f"{field_name} exceeds maximum length of {max_length} characters "
            f"(got {len(value)})"
        )


class MutationRateLimiter:
    def __init__(self, max_mutations: int = 60, window_seconds: int = 60):
        self.max_mutations = max_mutations
        self.window_seconds = window_seconds
        self._windows: dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, caller_id: str) -> None:
        async with self._lock:
            now = time.monotonic()
            window = self._windows[caller_id]
            cutoff = now - self.window_seconds

            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= self.max_mutations:
                raise ToolError(
                    f"Rate limit exceeded: {self.max_mutations} mutations per "
                    f"{self.window_seconds}s. Try again shortly."
                )
            window.append(now)

"""Conservative request pacing shared by the bundled workers.

This module deliberately does not try to disguise traffic or bypass access
controls.  It makes authorised/public archival jobs more reliable by keeping a
small per-process gap between requests and by treating a server-imposed pause
as a reason to slow down, not a reason to retry aggressively.
"""

import asyncio
import time


class CooperativePacer:
    """Serialise outbound calls at a courteous fixed interval."""

    def __init__(self, min_interval=0.7, max_interval=2.5):
        self.baseline_interval = max(0.0, float(min_interval))
        self.min_interval = self.baseline_interval
        self.max_interval = max(self.min_interval, float(max_interval))
        self._next_allowed_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        """Wait until the next request can be sent and reserve its slot."""
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_allowed_at = time.monotonic() + self.min_interval

    def slow_down(self, multiplier=1.6):
        """Increase future spacing after a transient failure or 429 response."""
        self.min_interval = min(self.max_interval, self.min_interval * max(1.0, multiplier))

    def recover(self, multiplier=0.94):
        """Gradually return to the configured baseline after successful calls."""
        self.min_interval = max(
            self.baseline_interval,
            self.min_interval * min(1.0, multiplier),
        )

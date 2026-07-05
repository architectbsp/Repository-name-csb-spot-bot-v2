from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(slots=True)
class RateLimiter:
    max_requests: int
    period: timedelta
    _requests: deque[datetime] = field(default_factory=deque)

    def _cleanup(self) -> None:
        cutoff = datetime.utcnow() - self.period

        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()

    def record_request(self) -> None:
        self._cleanup()
        self._requests.append(datetime.utcnow())

    def can_request(self) -> bool:
        self._cleanup()
        return len(self._requests) < self.max_requests

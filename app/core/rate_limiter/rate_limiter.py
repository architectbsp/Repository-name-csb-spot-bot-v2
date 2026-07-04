from __future__ import annotations

from collections import deque
from datetime import datetime


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        period: float,
    ) -> None:
        self._max_requests = max_requests
        self._period = period
        self._requests: deque[datetime] = deque()

    def record_request(self) -> None:
        self._requests.append(datetime.now())

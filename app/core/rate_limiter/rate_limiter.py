from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


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

    def _cleanup(self) -> None:
        threshold = datetime.now() - timedelta(seconds=self._period)

        while self._requests and self._requests[0] < threshold:
            self._requests.popleft()

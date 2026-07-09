from __future__ import annotations

from collections import deque
import time
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
        self._cleanup()
        self._requests.append(datetime.now())

    def can_request(self) -> bool:
        self._cleanup()
        return len(self._requests) < self._max_requests

    def remaining(self) -> int:
        self._cleanup()
        return max(0, self._max_requests - len(self._requests))

    def request_count(self) -> int:
        self._cleanup()
        return len(self._requests)

    def clear(self) -> None:
        self._requests.clear()

    def _cleanup(self) -> None:
        threshold = datetime.now() - timedelta(seconds=self._period)

        while self._requests and self._requests[0] < threshold:
            self._requests.popleft()


    def wrap(self, operation):
        while not self.can_request():
            time.sleep(0.05)
        self.record_request()
        return operation()

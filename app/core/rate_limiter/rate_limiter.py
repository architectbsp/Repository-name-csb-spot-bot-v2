from __future__ import annotations

from collections import deque
from datetime import datetime


class RateLimiter:
    def __init__(self) -> None:
        self._requests: deque[datetime] = deque()

    def record_request(self) -> None:
        self._requests.append(datetime.now())

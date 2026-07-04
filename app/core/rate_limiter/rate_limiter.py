from __future__ import annotations

from collections import deque
from datetime import datetime


class RateLimiter:
    def __init__(self) -> None:
        self._requests: deque[datetime] = deque()

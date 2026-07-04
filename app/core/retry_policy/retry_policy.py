from __future__ import annotations


class RetryPolicy:
    def __init__(
        self,
        max_attempts: int,
        delay: float,
    ) -> None:
        self._max_attempts = max_attempts
        self._delay = delay

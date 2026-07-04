from __future__ import annotations


class Timeout:
    def __init__(
        self,
        seconds: float,
    ) -> None:
        self._seconds = seconds

    def seconds(self) -> float:
        return self._seconds

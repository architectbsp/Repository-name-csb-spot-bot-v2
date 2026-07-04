from __future__ import annotations


class Timeout:
    def __init__(
        self,
        seconds: float,
    ) -> None:
        self._seconds = seconds

    def seconds(self) -> float:
        return self._seconds

    def is_disabled(self) -> bool:
        return self._seconds <= 0

    def __repr__(self) -> str:
        return f"Timeout(seconds={self._seconds})"

    def __str__(self) -> str:
        return self.__repr__()

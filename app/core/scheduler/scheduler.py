from __future__ import annotations

from collections.abc import Callable
from typing import Any


class Scheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, job: Callable[..., Any]) -> None:
        self._jobs[name] = job

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)

    def has_job(self, name: str) -> bool:
        return name in self._jobs

    @property
    def jobs(self) -> dict[str, Callable[..., Any]]:
        return self._jobs.copy()

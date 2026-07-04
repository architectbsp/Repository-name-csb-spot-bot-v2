from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Job:
    name: str
    interval: float
    callback: Callable[..., Any]
    enabled: bool = True
    running: bool = False
    last_run: datetime | None = None
    next_run: datetime | None = None

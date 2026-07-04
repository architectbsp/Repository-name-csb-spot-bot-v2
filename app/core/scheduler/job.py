from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Job:
    name: str
    interval: float
    callback: Callable[..., Any]
    enabled: bool = True

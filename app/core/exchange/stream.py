from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class PriceStream(ABC):
    @abstractmethod
    def start(
        self,
        symbols: list[str],
        callback: Callable[[str, dict[str, Any]], None],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_symbols(
        self,
        symbols: list[str],
    ) -> None:
        raise NotImplementedError

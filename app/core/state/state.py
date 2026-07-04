from enum import Enum, auto


class CoinState(Enum):
    IDLE = auto()

    WATCHING_UP = auto()
    WATCHING_DOWN = auto()

    READY_TO_BUY = auto()

    POSITION_OPEN = auto()
    TRAILING = auto()

    STOPPED = auto()
    TIMEOUT = auto()
    CLOSED = auto()

    COOLDOWN = auto()

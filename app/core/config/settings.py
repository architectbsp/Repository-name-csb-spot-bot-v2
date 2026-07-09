import os

from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class RiskSettings:
    max_daily_loss_percent: float = 20.0
    max_open_positions: int = 10
    capital_per_trade_percent: float = 10.0
    cooldown_hours: int = 4
    break_even_activation_percent: float = 10.0
    stop_loss_percent: float = 5.0
    trailing_activation_percent: float = 10.0
    trailing_percent: float = 5.0


@dataclass(slots=True)
class StrategySettings:
    watch_percent: float = 2.5
    entry_percent: float = 6.0
    take_profit_activation: float = 10.0
    stop_loss_percent: float = 5.0
    trailing_percent: float = 5.0
    min_volume_usd: float = 250_000.0
    max_position_hours: int = 24
    scan_interval_seconds: int = 300


@dataclass(slots=True)
class ConnectivitySettings:
    reconnect_interval_seconds: int = 10


@dataclass(slots=True)
class RetryPolicySettings:
    max_attempts: int = 3
    delay: float = 60.0


@dataclass(slots=True)
class TimeoutSettings:
    seconds: float = 30.0


@dataclass(slots=True)
class RateLimiterSettings:
    max_requests: int = 10
    period: float = 1.0


@dataclass(slots=True)
class TimerSettings:
    duration_seconds: int = 300


@dataclass(slots=True)
class ExchangeSettings:
    exchange: str = os.getenv("EXCHANGE", "binance").lower()
    api_key: str = os.getenv("EXCHANGE_API_KEY", "")
    api_secret: str = os.getenv("EXCHANGE_API_SECRET", "")
    testnet: bool = os.getenv("EXCHANGE_TESTNET", "true").lower() == "true"


@dataclass(slots=True)
class AppSettings:
    risk: RiskSettings = field(default_factory=RiskSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    connectivity: ConnectivitySettings = field(default_factory=ConnectivitySettings)
    exchange: ExchangeSettings = field(default_factory=ExchangeSettings)
    retry_policy: RetryPolicySettings = field(default_factory=RetryPolicySettings)
    timeout: TimeoutSettings = field(default_factory=TimeoutSettings)
    rate_limiter: RateLimiterSettings = field(default_factory=RateLimiterSettings)
    timer: TimerSettings = field(default_factory=TimerSettings)


settings = AppSettings()

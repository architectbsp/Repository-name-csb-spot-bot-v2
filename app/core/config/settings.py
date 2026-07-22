import os

from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class RiskSettings:
    """Risk parameters. Values must match docs/BUSINESS_RULES.md exactly.

    RiskManager is the sole owner of every risk-related number; Strategy
    must never carry its own copy of these (see the now-removed duplicate
    fields that used to live on StrategySettings -- that duplication is
    exactly the kind of config drift BUSINESS_RULES.md forbids).
    """

    max_daily_loss_percent: float = 20.0
    max_open_positions: int = 10
    cooldown_hours: int = 4

    # BUSINESS_RULES.md §7 Scenario 1 / §8: hard stop is 10% below entry.
    stop_loss_percent: float = 10.0
    # BUSINESS_RULES.md §8 Stop Loss / Trailing Stop Integration:
    # break-even and trailing activation share this single 2.0% threshold.
    trailing_activation_percent: float = 2.0
    # BUSINESS_RULES.md §8: "callback rate" -- trail 2.5% below the peak.
    trailing_percent: float = 2.5

    # Sprint 3 -- Scale Out / Partial Take Profit (docs/BUSINESS_RULES.md
    # §8 Order Execution Safety / Position Lifecycle): once unrealized
    # profit reaches this threshold, sell partial_tp_sell_percent% of the
    # position and keep managing the remainder normally. 0 (or below)
    # disables the feature entirely -- the existing single-exit behavior
    # is preserved unless an operator explicitly turns this on.
    partial_tp_activation_percent: float = 0.0
    partial_tp_sell_percent: float = 50.0

    # BUSINESS_RULES.md §8 Position Size: dynamic liquidity-based sizing.
    # Never commit more than 99.5% of the balance to a single trade
    # (headroom for commission/slippage).
    max_balance_utilization_percent: float = 99.5
    # Never commit more than 0.1% ("binde 1") of a coin's 24h quote
    # volume to a single trade.
    max_volume_share_percent: float = 0.1


@dataclass(slots=True)
class StrategySettings:
    """Strategy parameters. Values must match docs/BUSINESS_RULES.md exactly."""

    # BUSINESS_RULES.md §5 FSM: +/-2.5% moves a coin into WATCH_RISING/WATCH_FALLING.
    watch_percent: float = 2.5
    # BUSINESS_RULES.md §5 FSM: +6% recovery promotes WATCH_RISING to BUY_PENDING.
    entry_percent: float = 6.0

    # BUSINESS_RULES.md §10 Volume Filter: minimum 24h volume is 250,000 USD.
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

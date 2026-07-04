from dataclasses import dataclass, field


@dataclass(slots=True)
class RiskSettings:
    max_daily_loss_percent: float = 20.0
    max_open_positions: int = 10
    capital_per_trade_percent: float = 10.0
    cooldown_hours: int = 4


@dataclass(slots=True)
class StrategySettings:
    watch_percent: float = 2.5
    entry_percent: float = 6.0
    take_profit_activation: float = 10.0
    stop_loss_percent: float = 5.0
    trailing_percent: float = 5.0
    min_volume_usd: float = 250_000.0
    max_position_hours: int = 24


@dataclass(slots=True)
class ConnectivitySettings:
    reconnect_interval_seconds: int = 10


@dataclass(slots=True)
class AppSettings:
    risk: RiskSettings = field(default_factory=RiskSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    connectivity: ConnectivitySettings = field(default_factory=ConnectivitySettings)


settings = AppSettings()

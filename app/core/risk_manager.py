import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.domain.position import CloseReason, Position
from app.core.scheduler.job import Job
from app.core.services.order_execution import ExecutionOutcome, OrderExecutionService
from app.core.services.volatility import (
    compute_atr,
    compute_realized_volatility_percent,
)
from app.core.trading.models import TradeRequest, TradeSide


logger = logging.getLogger(__name__)

_DAILY_RESET_JOB_NAME = "risk_manager_daily_reset"
_DAILY_RESET_CHECK_INTERVAL_SECONDS = 60

_MAX_DURATION_JOB_NAME = "risk_manager_max_duration_check"
_MAX_DURATION_CHECK_INTERVAL_SECONDS = 60

# Sprint 8: fixed OHLCV timeframe for ATR / realized-vol sizing. Not a
# Settings knob (SETTINGS_SCHEMA is numeric-only); 1h + atr_period=14
# gives a ~14h lookback appropriate for this spot swing bot.
_SIZING_OHLCV_TIMEFRAME = "1h"
_SIZING_MODE_LIQUIDITY_ONLY = 0
_SIZING_MODE_HYBRID = 1
_SIZING_MODE_FIXED_RISK = 2
_SIZING_MODE_ATR = 3
_SIZING_MODE_KELLY = 4
# Clamp so a dead-flat market can't blow the vol-scaled size past the
# balance cap, and a spike can't shrink it to a dust amount.
_VOL_SCALE_MIN = 0.25
_VOL_SCALE_MAX = 1.0
# Never let Kelly size more than this fraction of balance.
_KELLY_HARD_CAP = 0.25

# Sprint 3: which CloseReason to record depending on which stop level
# actually triggered (hard vs break-even vs trailing).
_STOP_STAGE_CLOSE_REASONS = {
    "HARD": CloseReason.STOP_LOSS,
    "BREAK_EVEN": CloseReason.BREAK_EVEN_STOP,
    "TRAILING": CloseReason.TRAILING_STOP,
}


def _raw_price(ticker, fallback: float) -> str:
    """
    docs/BUSINESS_RULES.md §9: prefer the untouched exchange string over a
    reformatted float when logging an exchange-sourced price.
    """
    raw = getattr(ticker, "raw_last_price", None)
    return raw if raw is not None else f"{fallback:.8f}"


class RiskManager:
    _DEPENDENCY_NAMES = (
        "exchange",
        "exchange_manager",
        "scheduler",
        "event_bus",
        "rate_limiter",
        "retry_policy",
        "timeout",
        "timer",
        "stopwatch",
        "position_manager",
        "order_validator",
        "trade_journal",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._exchange = None
        self._exchange_manager = None
        self._scheduler = None
        self._event_bus = None
        self._rate_limiter = None
        self._retry_policy = None
        self._timeout = None
        self._timer = None
        self._stopwatch = None
        self._position_manager = None
        self._order_validator = None
        self._trade_journal = None
        self._config = None

        # Daily loss circuit-breaker state (docs/BUSINESS_RULES.md §8).
        self._trading_day: date | None = None
        self._day_start_balance: float | None = None
        self._realized_pnl_today: float = 0.0
        # Sprint 11: fire risk.daily_loss_limit at most once per UTC day.
        self._daily_loss_alerted: bool = False
        # Sprint 3: set by emergency_exit_all until operator unfreezes.
        self._entries_frozen: bool = False

        # Sprint 4: built lazily on first real order submission (see
        # _get_order_execution) so every setter above has already run by
        # the time it's constructed, regardless of wiring order.
        self._order_execution: OrderExecutionService | None = None

    def initialize(self) -> None:
        self._initialized = True

        if self._scheduler is not None and not self._scheduler.has_job(
            _DAILY_RESET_JOB_NAME
        ):
            job = Job(
                name=_DAILY_RESET_JOB_NAME,
                interval=_DAILY_RESET_CHECK_INTERVAL_SECONDS,
                callback=self._check_daily_reset,
            )
            self._scheduler.register(job)
            self._scheduler.schedule(job)

        if self._scheduler is not None and not self._scheduler.has_job(
            _MAX_DURATION_JOB_NAME
        ):
            duration_job = Job(
                name=_MAX_DURATION_JOB_NAME,
                interval=_MAX_DURATION_CHECK_INTERVAL_SECONDS,
                callback=self._check_max_duration_positions,
            )
            self._scheduler.register(duration_job)
            self._scheduler.schedule(duration_job)

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("RiskManager is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def set_exchange(self, exchange):
        self._exchange = exchange

    def set_exchange_manager(self, exchange_manager):
        self._exchange_manager = exchange_manager

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def set_rate_limiter(self, rate_limiter):
        self._rate_limiter = rate_limiter

    def set_retry_policy(self, retry_policy):
        self._retry_policy = retry_policy

    def set_timeout(self, timeout):
        self._timeout = timeout

    def set_timer(self, timer):
        self._timer = timer

    def set_stopwatch(self, stopwatch):
        self._stopwatch = stopwatch

    def set_position_manager(self, position_manager):
        self._position_manager = position_manager

    def set_order_validator(self, order_validator):
        self._order_validator = order_validator

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def set_order_execution(self, order_execution: OrderExecutionService) -> None:
        """Mainly for tests -- production wiring builds this lazily in
        _get_order_execution() from the already-wired exchange_manager /
        retry_policy / timeout dependencies."""
        self._order_execution = order_execution

    def _get_order_execution(self) -> OrderExecutionService:
        if self._order_execution is None:
            self._order_execution = OrderExecutionService(
                self._exchange_manager,
                retry_policy=self._retry_policy,
                timeout=self._timeout,
                pending_timeout_seconds=30.0,
                position_manager=self._position_manager,
            )
        else:
            # Keep position_manager in sync if OES was built early / in tests.
            self._order_execution.set_position_manager(self._position_manager)
        return self._order_execution

    @property
    def order_execution(self) -> OrderExecutionService:
        return self._get_order_execution()

    def set_config(self, config):
        self._config = config

    def on_config_updated(self, event) -> None:
        """EventBus `config.updated` -- risk knobs are read live via
        `self._risk` on every decision; no local cache to invalidate."""
        return None

    @property
    def _risk(self):
        if self._config is None:
            raise RuntimeError("RiskManager config dependency is not set.")
        return self._config.risk

    def calculate_position_size(
        self,
        balance: float,
        volume_24h: float | None = None,
        *,
        price: float | None = None,
        symbol: str | None = None,
        exchange_type=None,
    ) -> float:
        """
        Position sizing (docs/BUSINESS_RULES.md §8).

        Always applies hard safety caps (balance + liquidity). Then, based
        on `position_sizing_mode`:

          0 liquidity-only
          1 hybrid (default): Fixed Risk + ATR + realized-vol
          2 Fixed Risk only
          3 Volatility / ATR-based (ATR + optional realized-vol scale)
          4 Kelly Criterion (from closed Trade Journal stats)

        Missing candle / journal data never blocks a trade -- those caps
        are skipped and sizing falls back to the hard safety floors.
        """
        if balance <= 0:
            return 0.0

        balance_dec = Decimal(str(balance))
        balance_cap = balance_dec * Decimal(
            str(self._risk.max_balance_utilization_percent)
        ) / Decimal("100")

        caps: list[Decimal] = [balance_cap]

        if volume_24h is not None and volume_24h > 0:
            volume_dec = Decimal(str(volume_24h))
            liquidity_cap = volume_dec * Decimal(
                str(self._risk.max_volume_share_percent)
            ) / Decimal("100")
            caps.append(liquidity_cap)

        sizing_mode = int(
            getattr(self._risk, "position_sizing_mode", _SIZING_MODE_HYBRID)
        )

        use_risk = sizing_mode in (
            _SIZING_MODE_HYBRID,
            _SIZING_MODE_FIXED_RISK,
        )
        use_atr = sizing_mode in (
            _SIZING_MODE_HYBRID,
            _SIZING_MODE_ATR,
        )
        use_vol = sizing_mode in (
            _SIZING_MODE_HYBRID,
            _SIZING_MODE_ATR,
        )
        use_kelly = sizing_mode == _SIZING_MODE_KELLY

        if use_risk:
            risk_cap = self._risk_based_cap(balance_dec)
            if risk_cap is not None:
                caps.append(risk_cap)

        candles = (
            self._fetch_sizing_candles(symbol, exchange_type)
            if (use_atr or use_vol)
            else []
        )

        if use_atr and candles and price is not None and price > 0:
            atr_cap = self._atr_based_cap(balance_dec, price, candles)
            if atr_cap is not None:
                caps.append(atr_cap)

        if use_vol and candles:
            vol_cap = self._volatility_based_cap(balance_cap, candles)
            if vol_cap is not None:
                caps.append(vol_cap)

        if use_kelly:
            kelly_cap = self._kelly_based_cap(balance_dec)
            if kelly_cap is not None:
                caps.append(kelly_cap)

        return float(min(caps))

    def _risk_based_cap(self, balance: Decimal) -> Decimal | None:
        """Size so that a hard-stop hit loses at most risk_per_trade% of
        the treasury. None when stop_loss_percent is unset/zero."""
        stop_pct = float(getattr(self._risk, "stop_loss_percent", 0.0) or 0.0)
        risk_pct = float(getattr(self._risk, "risk_per_trade_percent", 0.0) or 0.0)

        if stop_pct <= 0 or risk_pct <= 0:
            return None

        risk_amount = balance * Decimal(str(risk_pct)) / Decimal("100")
        return risk_amount / (Decimal(str(stop_pct)) / Decimal("100"))

    def _atr_based_cap(
        self,
        balance: Decimal,
        price: float,
        candles,
    ) -> Decimal | None:
        """Size so that an ATR*multiplier move against the position loses
        at most risk_per_trade% of the treasury."""
        period = int(getattr(self._risk, "atr_period", 14) or 14)
        multiplier = float(getattr(self._risk, "atr_multiplier", 2.0) or 0.0)
        risk_pct = float(getattr(self._risk, "risk_per_trade_percent", 0.0) or 0.0)

        if multiplier <= 0 or risk_pct <= 0 or price <= 0:
            return None

        atr = compute_atr(candles, period=period)
        if atr is None or atr <= 0:
            return None

        stop_distance = atr * multiplier
        if stop_distance <= 0:
            return None

        risk_amount = balance * Decimal(str(risk_pct)) / Decimal("100")
        # position_value * (stop_distance / price) = risk_amount
        # => position_value = risk_amount * price / stop_distance
        return risk_amount * Decimal(str(price)) / Decimal(str(stop_distance))

    def _volatility_based_cap(
        self,
        balance_cap: Decimal,
        candles,
    ) -> Decimal | None:
        """Scale the balance cap by target_vol / realized_vol, clamped so
        a quiet market never exceeds the balance cap and a wild market
        never sizes below VOL_SCALE_MIN of it."""
        target = float(getattr(self._risk, "volatility_target_percent", 0.0) or 0.0)
        lookback = int(getattr(self._risk, "volatility_lookback", 20) or 20)

        if target <= 0:
            return None

        realized = compute_realized_volatility_percent(candles, lookback=lookback)
        if realized is None or realized <= 0:
            return None

        scale = target / realized
        scale = max(_VOL_SCALE_MIN, min(_VOL_SCALE_MAX, scale))
        return balance_cap * Decimal(str(scale))

    def _kelly_based_cap(self, balance: Decimal) -> Decimal | None:
        """
        Kelly Criterion stake from closed Trade Journal stats:

            f* = W - (1 - W) / R
            size = balance * kelly_fraction * f*

        where W = win rate and R = avg_win / abs(avg_loss). Returns None
        until `kelly_min_trades` closed trades exist (or f* <= 0).
        """
        if self._trade_journal is None:
            return None

        from app.core.domain.trade_journal import STATUS_CLOSED

        min_trades = int(getattr(self._risk, "kelly_min_trades", 10) or 10)
        fraction = float(getattr(self._risk, "kelly_fraction", 0.5) or 0.0)
        if fraction <= 0 or min_trades <= 0:
            return None

        closed = [
            entry
            for entry in self._trade_journal.list_all()
            if entry.status == STATUS_CLOSED and entry.pnl is not None
        ]
        if len(closed) < min_trades:
            return None

        wins = [entry.pnl for entry in closed if entry.pnl > 0]
        losses = [entry.pnl for entry in closed if entry.pnl < 0]
        if not wins or not losses:
            return None

        win_rate = len(wins) / len(closed)
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        if avg_loss <= 0:
            return None

        reward_risk = avg_win / avg_loss
        f_star = win_rate - ((1.0 - win_rate) / reward_risk)
        if f_star <= 0:
            return None

        stake = min(f_star * fraction, _KELLY_HARD_CAP)
        return balance * Decimal(str(stake))

    def _fetch_sizing_candles(self, symbol: str | None, exchange_type):
        if (
            symbol is None
            or exchange_type is None
            or self._exchange_manager is None
        ):
            return []

        period = int(getattr(self._risk, "atr_period", 14) or 14)
        lookback = int(getattr(self._risk, "volatility_lookback", 20) or 20)
        # +2 for the prior-close needed by ATR / return math.
        limit = max(period, lookback) + 2

        try:
            return self._exchange_manager.fetch_ohlcv(
                exchange_type,
                symbol,
                timeframe=_SIZING_OHLCV_TIMEFRAME,
                limit=limit,
            )
        except Exception:
            logger.debug(
                "[RISK] Sizing OHLCV fetch failed for %s -- skipping ATR/vol caps",
                symbol,
                exc_info=True,
            )
            return []

    def has_sufficient_balance(
        self,
        balance: float,
        volume_24h: float | None = None,
        *,
        price: float | None = None,
        symbol: str | None = None,
        exchange_type=None,
    ) -> bool:
        return self.calculate_position_size(
            balance,
            volume_24h,
            price=price,
            symbol=symbol,
            exchange_type=exchange_type,
        ) > 0.0

    def is_daily_loss_limit_reached(self, daily_loss_percent: float) -> bool:
        return daily_loss_percent >= self._risk.max_daily_loss_percent

    def _sync_trading_day(self, balance: float) -> None:
        """
        Resets the daily-loss tracking window at 00:00 UTC
        (docs/BUSINESS_RULES.md §8: the circuit breaker resets at UTC
        midnight, not on a rolling 24h timer). `balance` becomes the new
        day's starting treasury the first time each UTC day is observed.
        """
        today = datetime.now(UTC).date()

        if self._trading_day == today:
            return

        self._trading_day = today
        self._day_start_balance = balance
        self._realized_pnl_today = 0.0
        self._daily_loss_alerted = False

        logger.info(
            "[RISK] New UTC trading day started; day_start_balance=%.8f",
            balance,
        )

    def _check_daily_reset(self) -> None:
        """Scheduled job: keeps the UTC day boundary accurate even on
        days where no new trade is attempted (open_position() is the
        other place this gets synced, opportunistically)."""
        if self._exchange_manager is None:
            return

        balance = self._total_quote_balance()
        if balance is None:
            logger.debug(
                "[RISK] Skipping daily-reset check: exchange unavailable"
            )
            return

        self._sync_trading_day(balance)

    def _total_quote_balance(self) -> float | None:
        """Sprint 18: sum free quote balances across every enabled
        exchange for the shared daily-loss treasury snapshot."""
        if self._exchange_manager is None:
            return None

        try:
            exchange_types = self._exchange_manager.enabled_exchange_types()
        except Exception:
            return None

        total = 0.0
        any_ok = False
        for exchange_type in exchange_types:
            try:
                total += float(
                    self._exchange_manager.get_quote_balance(exchange_type)
                )
                any_ok = True
            except Exception:
                logger.debug(
                    "[RISK] Quote balance unavailable for %s",
                    exchange_type,
                    exc_info=True,
                )

        return total if any_ok else None

    def current_daily_loss_percent(self) -> float:
        """Realized loss so far today, as a percentage of the day's
        starting treasury (0 if no loss, or if the day hasn't been
        established yet)."""
        if not self._day_start_balance or self._day_start_balance <= 0:
            return 0.0

        loss = max(0.0, -self._realized_pnl_today)
        return (loss / self._day_start_balance) * 100

    def realized_pnl_today(self) -> float:
        """Sprint 12 -- signed realized PnL accumulated since the UTC
        day boundary (positive = profit, negative = loss)."""
        return self._realized_pnl_today

    def day_start_balance(self) -> float | None:
        """Sprint 12 -- treasury snapshot taken at the start of the
        current UTC trading day, or None before the first sync."""
        return self._day_start_balance

    def _record_realized_pnl(self, pnl: float) -> None:
        self._realized_pnl_today += pnl

        if self.is_daily_loss_limit_reached(self.current_daily_loss_percent()):
            logger.warning(
                "[RISK] Daily loss limit reached (%.2f%% >= %.2f%%); "
                "halting new trades until 00:00 UTC",
                self.current_daily_loss_percent(),
                self._risk.max_daily_loss_percent,
            )
            if not self._daily_loss_alerted:
                self._daily_loss_alerted = True
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "risk.daily_loss_limit",
                        {
                            "daily_loss_percent": (
                                self.current_daily_loss_percent()
                            ),
                            "limit_percent": self._risk.max_daily_loss_percent,
                        },
                    )

    def can_open_trade(
        self,
        *,
        balance: float,
        daily_loss_percent: float,
        open_positions: int,
    ) -> bool:
        if self._entries_frozen or (
            self._position_manager is not None
            and getattr(self._position_manager, "entries_frozen", False)
        ):
            logger.warning("[RISK] Trade rejected: entries frozen after emergency exit")
            return False

        if self.is_daily_loss_limit_reached(daily_loss_percent):
            logger.warning("[RISK] Trade rejected: daily_loss_limit reached")
            return False

        if open_positions >= self._risk.max_open_positions:
            logger.warning("[RISK] Trade rejected: max_open_positions reached")
            return False

        if not self.has_sufficient_balance(balance):
            logger.warning("[RISK] Trade rejected: insufficient_balance")
            return False

        if not self._is_within_trading_hours():
            return False

        logger.debug("[RISK] Trade accepted")
        return True

    def _is_within_trading_hours(self) -> bool:
        """Blocks new entries outside quiet hours / weekends when enabled."""
        from app.core.services.trading_hours import block_reason, is_entry_allowed

        strategy = getattr(self._config, "strategy", None)
        if strategy is None:
            return True

        enabled = bool(int(getattr(strategy, "trading_hours_enabled", 0) or 0))
        weekend_closed = bool(int(getattr(strategy, "weekend_closed", 1) or 0))
        quiet_start = int(getattr(strategy, "quiet_start_hour_utc", 2) or 0)
        quiet_end = int(getattr(strategy, "quiet_end_hour_utc", 5) or 0)

        allowed = is_entry_allowed(
            enabled=enabled,
            weekend_closed=weekend_closed,
            quiet_start_hour_utc=quiet_start,
            quiet_end_hour_utc=quiet_end,
        )
        if allowed:
            return True

        reason = block_reason(
            enabled=enabled,
            weekend_closed=weekend_closed,
            quiet_start_hour_utc=quiet_start,
            quiet_end_hour_utc=quiet_end,
        )
        logger.warning("[RISK] Trade rejected: trading_hours (%s)", reason)
        return False

    @staticmethod
    def create_trade_request(
        *,
        symbol: str,
        quantity: Decimal,
        side: TradeSide = TradeSide.BUY,
    ) -> TradeRequest:
        return TradeRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )

    _NEEDS_MANUAL_REVIEW = frozenset(
        {
            ExecutionOutcome.UNRECONCILED,
            ExecutionOutcome.UNKNOWN_STATUS,
            ExecutionOutcome.QUARANTINED,
            ExecutionOutcome.NETWORK_FAILED,
        }
    )

    def _publish_execution_alert(
        self,
        *,
        symbol: str,
        side: str,
        execution,
    ) -> None:
        """
        Sprint 4: surfaces execution outcomes that cannot be resolved
        automatically (unreconciled / unknown-status / quarantined /
        network-failed / ambiguous submit timeout) as an event so
        Telegram / dashboard subscribers can notify an operator.
        """
        needs_review = execution.outcome in self._NEEDS_MANUAL_REVIEW or (
            execution.outcome == ExecutionOutcome.TIMED_OUT
            and getattr(execution, "is_ambiguous", False)
        )
        if not needs_review:
            return

        logger.critical(
            "[EXEC ALERT] symbol=%s side=%s outcome=%s error=%s -- "
            "manual review required",
            symbol,
            side,
            execution.outcome,
            execution.error,
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                "order.needs_manual_review",
                {
                    "symbol": symbol,
                    "side": side,
                    "outcome": execution.outcome,
                    "error": execution.error,
                },
            )

    @staticmethod
    def _is_filled_buy_result(result) -> bool:
        if result is None:
            return False

        return (
            str(getattr(result, "status", "")).upper() in {"CLOSED", "FILLED"}
            and float(getattr(result, "filled_quantity", 0.0) or 0.0) > 0.0
        )

    def open_position(
        self,
        *,
        exchange_type,
        symbol: str,
        price: float,
        volume_24h: float | None = None,
    ) -> Position | None:
        """
        Full buy-side trade-permission and execution workflow.

        This is the single entry point through which a new position may be
        opened: balance validation, position sizing, trade-permission
        checks, order validation and order submission all happen here.

        BUSINESS_RULES.md #12 forbids Strategy from sending exchange orders
        directly, so Strategy must only call this method with a candidate
        signal (symbol/price/volume_24h) and react to the returned Position
        (or None on rejection). Risk parameters (stop loss %, position
        sizing caps, daily loss limit) all live here, not in Strategy, so
        there is exactly one place they can be configured or drift.
        """
        if (
            self._exchange_manager is None
            or self._position_manager is None
            or self._order_validator is None
        ):
            logger.error(
                "[RISK] open_position missing required dependencies "
                "(exchange_manager=%s position_manager=%s order_validator=%s)",
                self._exchange_manager is not None,
                self._position_manager is not None,
                self._order_validator is not None,
            )
            return None

        # Size against THIS venue's free balance (never spend Bybit
        # money on a Binance order). Daily-loss treasury is the sum
        # across every enabled venue (Sprint 18 shared risk budget).
        balance = self._exchange_manager.get_quote_balance(exchange_type)
        treasury = self._total_quote_balance()
        self._sync_trading_day(
            treasury if treasury is not None else balance
        )

        if not self.can_open_trade(
            balance=balance,
            daily_loss_percent=self.current_daily_loss_percent(),
            open_positions=self._position_manager.open_count(),
        ):
            return None

        if self._position_manager.is_open(symbol, exchange=exchange_type):
            logger.warning(
                "[RISK] Duplicate BUY blocked for %s -- open position already exists",
                symbol,
            )
            return None

        position_value = self.calculate_position_size(
            balance,
            volume_24h,
            price=price,
            symbol=symbol,
            exchange_type=exchange_type,
        )

        if position_value <= 0:
            return None

        quantity = position_value / price

        trade = self.create_trade_request(
            symbol=symbol,
            quantity=Decimal(str(quantity)),
        )

        validated_trade = self._order_validator.validate(
            exchange_type,
            trade,
        )

        # Sprint 4: duplicate-order guard, retry/timeout policy, pending
        # order reconciliation and unknown-status handling all live in
        # OrderExecutionService -- RiskManager never talks to
        # ExchangeManager.execute_trade() directly anymore.
        execution = self._get_order_execution().execute(
            exchange_type,
            validated_trade,
        )

        self._publish_execution_alert(symbol=symbol, side="BUY", execution=execution)

        if not execution.is_filled:
            logger.warning(
                "[RISK] Buy order not filled for %s (outcome=%s error=%s)",
                symbol,
                execution.outcome,
                execution.error,
            )
            return None

        result = execution.order_result

        if not self._is_filled_buy_result(result):
            logger.warning(
                "[RISK] Buy order not filled for %s (status=%s)",
                symbol,
                getattr(result, "status", None),
            )
            return None

        entry_price = result.average_price

        if entry_price is None or entry_price <= 0:
            entry_price = price

        stop_price = entry_price * (1 - self._risk.stop_loss_percent / 100)

        position = Position(
            symbol=symbol,
            entry_price=entry_price,
            quantity=float(result.filled_quantity),
            opened_at=datetime.now(UTC),
            stop_price=stop_price,
            exchange=exchange_type,
            entry_commission=getattr(result, "fee_cost", None),
        )

        if not self._position_manager.add(position):
            logger.error(
                "[RISK] PositionManager rejected new position for %s",
                symbol,
            )
            return None

        logger.info(
            "[BUY EXECUTED] symbol=%s entry=%.8f qty=%.8f stop=%.8f",
            symbol,
            entry_price,
            position.quantity,
            stop_price,
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                "position.opened",
                {
                    "symbol": symbol,
                    "exchange": getattr(exchange_type, "name", exchange_type),
                    "entry_price": entry_price,
                    "quantity": position.quantity,
                    "stop_price": stop_price,
                    "position": position,
                },
            )

        return position

    def on_price_tick(
        self,
        ticker,
    ) -> None:
        logger.debug(
            "[RISK] Dependencies check: position_manager=%s exchange_manager=%s",
            self._position_manager is not None,
            self._exchange_manager is not None,
        )

        if (
            self._position_manager is None
            or self._exchange_manager is None
        ):
            return

        symbol = ticker.symbol

        position = self._position_manager.get(
            symbol,
            exchange=ticker.exchange,
        )

        if position is None:
            return

        if not self._running:
            return

        # Isolated data flow guard (docs/BUSINESS_RULES.md §10): a price
        # tick from exchange A must never be allowed to trigger a
        # stop-loss/trailing/break-even action on a position opened on
        # exchange B. Older positions with no recorded exchange (e.g.
        # legacy data) are still processed to avoid silently orphaning
        # them.
        if (
            position.exchange is not None
            and getattr(ticker, "exchange", None) is not None
            and position.exchange != ticker.exchange
        ):
            logger.debug(
                "[RISK] Ignoring tick for %s from %s; position was opened "
                "on %s",
                symbol,
                ticker.exchange,
                position.exchange,
            )
            return

        self.update_position(
            position,
            ticker,
        )

    def get_quote_balance(self, exchange_type) -> float | None:
        """Free quote wallet for journal / sizing callers."""
        if self._exchange_manager is None:
            return None
        try:
            return float(self._exchange_manager.get_quote_balance(exchange_type))
        except Exception:
            return None

    def update_position(
        self,
        position,
        ticker,
    ) -> None:
        if self._trade_journal is not None:
            try:
                self._trade_journal.record_price_update(
                    position.symbol,
                    float(ticker.last_price),
                    exchange=getattr(position, "exchange", None),
                )
            except Exception:
                logger.exception(
                    "[JOURNAL] price update failed symbol=%s",
                    position.symbol,
                )

        self.check_partial_take_profit(position, ticker)
        self.check_break_even(position, ticker)
        self.check_trailing(position, ticker)
        self.check_stop_loss(position, ticker)

    def check_partial_take_profit(self, position, ticker) -> None:
        """
        Sprint 3 -- Scale Out / Partial Take Profit: once unrealized
        profit reaches `risk.partial_tp_activation_percent`, sells
        `risk.partial_tp_sell_percent`% of the position and keeps
        managing the remainder normally (stop/break-even/trailing keep
        operating on the reduced quantity). Disabled by default
        (activation <= 0); fires at most once per position.
        """
        activation = self._risk.partial_tp_activation_percent

        if activation <= 0:
            return

        if getattr(position, "partial_exits_taken", 0) > 0:
            return

        if position.state.name != "OPEN":
            return

        profit = (
            (ticker.last_price - position.entry_price) / position.entry_price
        ) * 100

        if profit < activation:
            return

        sell_percent = self._risk.partial_tp_sell_percent
        sell_quantity = position.quantity * (sell_percent / 100)

        if sell_quantity <= 0 or sell_quantity >= position.quantity:
            return

        trade = TradeRequest(
            symbol=position.symbol,
            quantity=Decimal(str(sell_quantity)),
            side=TradeSide.SELL,
        )

        logger.info(
            "[PARTIAL TP] symbol=%s profit=%.2f%% selling=%.8f (%.0f%% of "
            "position)",
            position.symbol,
            profit,
            sell_quantity,
            sell_percent,
        )

        execution = self._get_order_execution().execute(ticker.exchange, trade)

        self._publish_execution_alert(
            symbol=position.symbol, side="SELL", execution=execution
        )

        if not execution.is_filled or execution.order_result is None:
            logger.warning(
                "[PARTIAL TP] Scale-out not filled for %s (outcome=%s "
                "error=%s)",
                position.symbol,
                execution.outcome,
                execution.error,
            )
            return

        result = execution.order_result
        exit_price = result.average_price or ticker.last_price
        filled_quantity = result.filled_quantity or sell_quantity

        realized = self._position_manager.scale_out(
            position.symbol,
            sell_quantity=filled_quantity,
            exit_price=exit_price,
            reason=CloseReason.PARTIAL_TP,
            exchange=position.exchange,
        )

        if realized is None:
            logger.error(
                "[PARTIAL TP] scale_out() rejected the fill for %s -- "
                "position left unchanged",
                position.symbol,
            )
            return

        # docs/BUSINESS_RULES.md §8 Daily Loss Limit: this partial exit's
        # PnL is realized right now, independent of whatever happens to
        # the remainder later.
        self._record_realized_pnl(realized)

        if self._trade_journal is not None:
            self._trade_journal.record_partial_exit(
                position.symbol,
                exit_price=exit_price,
                quantity=filled_quantity,
                realized_pnl=realized,
                reason=CloseReason.PARTIAL_TP,
                exchange=position.exchange,
                commission=getattr(result, "fee_cost", None),
            )

        logger.info(
            "[PARTIAL TP] symbol=%s sold=%.8f exit=%.8f realized_pnl=%.8f "
            "remaining_qty=%.8f",
            position.symbol,
            filled_quantity,
            exit_price,
            realized,
            position.quantity,
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                "position.partial_exit",
                {
                    "symbol": position.symbol,
                    "exchange": getattr(
                        position.exchange, "name", position.exchange
                    ),
                    "quantity": filled_quantity,
                    "exit_price": exit_price,
                    "realized_pnl": realized,
                },
            )

    def check_stop_loss(self, position, ticker) -> None:
        if position.stop_price is None:
            return

        last_price = ticker.last_price

        logger.debug(
            "[STOP CHECK] symbol=%s last=%s stop=%.8f triggered=%s",
            position.symbol,
            _raw_price(ticker, last_price),
            position.stop_price,
            last_price <= position.stop_price,
        )

        if last_price > position.stop_price:
            return

        logger.info(
            "[SELL TRIGGER] symbol=%s last=%s stop=%.8f",
            position.symbol,
            _raw_price(ticker, last_price),
            position.stop_price,
        )

        stage = getattr(position, "stop_stage", "HARD")
        reason = _STOP_STAGE_CLOSE_REASONS.get(stage, "STOP_LOSS")

        self._close_position_with_market_sell(
            position,
            exchange_type=ticker.exchange,
            fallback_price=last_price,
            reason=reason,
        )

    def manual_close(self, symbol: str) -> bool:
        """Sprint 3 alias for ``close_position_manually``."""
        return self.close_position_manually(symbol)

    def close_position_manually(self, symbol: str) -> bool:
        """
        Sprint 3 -- Manual Close: an operator-initiated exit, independent
        of any price/stop/duration trigger. Goes through the exact same
        OrderExecutionService pipeline (duplicate protection, retry,
        reconciliation) as every other exit path -- there is no
        "shortcut" order path anywhere in this class.

        Returns True if the position ends up CLOSED, False if it didn't
        exist, wasn't open, had no recorded exchange, or the sell could
        not be confirmed filled (in which case it remains OPEN and the
        operator can try again).
        """
        if self._position_manager is None:
            return False

        position = self._position_manager.get(symbol)

        if position is None or position.state.name != "OPEN":
            # Ambiguous symbol across venues -- try exact lookup failure.
            return False

        exchange_type = position.exchange

        if exchange_type is None:
            logger.error(
                "[MANUAL CLOSE] %s has no recorded exchange; refusing to "
                "guess which exchange to sell on",
                symbol,
            )
            return False

        logger.warning("[MANUAL CLOSE] Operator requested close for %s", symbol)

        self._close_position_with_market_sell(
            position,
            exchange_type=exchange_type,
            fallback_price=position.entry_price,
            reason=CloseReason.MANUAL_CLOSE,
        )

        return not self._position_manager.is_open(
            symbol,
            exchange=exchange_type,
        )

    def unfreeze_entries(self) -> None:
        """Clears the emergency-exit new-entry freeze."""
        self._entries_frozen = False
        if self._position_manager is not None and hasattr(
            self._position_manager, "unfreeze_new_entries"
        ):
            self._position_manager.unfreeze_new_entries()

    def emergency_exit_all(self) -> int:
        """
        Sprint 3 -- Emergency Exit: force-closes every open position
        immediately, regardless of price, stop level or state -- an
        operator "panic button" for going fully flat (e.g. ahead of
        maintenance, a black-swan event, or a manual risk decision this
        bot's own logic wouldn't otherwise make). Unlike the daily-loss
        circuit breaker (which only stops *new* trades from being
        opened), this actively exits every existing one and freezes
        new entries until ``unfreeze_entries()``.

        Returns how many positions were actually confirmed closed.
        """
        if self._position_manager is None:
            return 0

        open_positions = list(self._position_manager.get_open_positions())

        logger.critical(
            "[EMERGENCY EXIT] Operator triggered emergency exit for %d "
            "open position(s)",
            len(open_positions),
        )

        closed = 0

        for position in open_positions:
            exchange_type = position.exchange

            if exchange_type is None:
                logger.error(
                    "[EMERGENCY EXIT] %s has no recorded exchange; "
                    "skipping",
                    position.symbol,
                )
                continue

            self._close_position_with_market_sell(
                position,
                exchange_type=exchange_type,
                fallback_price=position.entry_price,
                reason=CloseReason.EMERGENCY_EXIT,
            )

            if not self._position_manager.is_open(
                position.symbol,
                exchange=position.exchange,
            ):
                closed += 1

        self._entries_frozen = True
        if hasattr(self._position_manager, "freeze_new_entries"):
            self._position_manager.freeze_new_entries()

        logger.critical(
            "[EMERGENCY EXIT] Closed %d/%d open position(s); new entries frozen",
            closed,
            len(open_positions),
        )

        return closed

    def _check_max_duration_positions(self) -> None:
        """
        docs/BUSINESS_RULES.md §8 "Maximum Position Duration": once a
        position has been open for `strategy.max_position_hours`, it must
        be closed with a market order regardless of where the price sits
        relative to the stop. Runs as a periodic scheduler job (like the
        cooldown and daily-reset jobs) so it fires even if no new tick
        happens to arrive for a stale symbol.
        """
        if self._position_manager is None or self._config is None:
            return

        max_hours = getattr(self._config.strategy, "max_position_hours", None)

        if not max_hours:
            return

        now = datetime.now(UTC)

        for position in list(self._position_manager.get_open_positions()):
            if position.state.name != "OPEN":
                continue

            age_hours = (now - position.opened_at).total_seconds() / 3600.0

            if age_hours < max_hours:
                continue

            exchange_type = position.exchange

            if exchange_type is None:
                logger.warning(
                    "[MAX DURATION] %s has no recorded exchange; skipping "
                    "forced close",
                    position.symbol,
                )
                continue

            logger.info(
                "[MAX DURATION] symbol=%s age_hours=%.2f limit=%s -- "
                "forcing close",
                position.symbol,
                age_hours,
                max_hours,
            )

            self._close_position_with_market_sell(
                position,
                exchange_type=exchange_type,
                fallback_price=position.entry_price,
                reason=CloseReason.MAX_DURATION,
            )

    def _close_position_with_market_sell(
        self,
        position,
        *,
        exchange_type,
        fallback_price: float,
        reason: str,
    ) -> None:
        if position.state.name != "OPEN":
            return

        trade = TradeRequest(
            symbol=position.symbol,
            quantity=Decimal(str(position.quantity)),
            side=TradeSide.SELL,
        )

        logger.info(
            "[SELL EXECUTE] symbol=%s quantity=%.8f reason=%s",
            position.symbol,
            position.quantity,
            reason,
        )

        execution = self._get_order_execution().execute(
            exchange_type,
            trade,
        )

        self._publish_execution_alert(
            symbol=position.symbol, side="SELL", execution=execution
        )

        result = execution.order_result

        if result is not None:
            logger.debug(
                "[SELL STATUS] outcome=%s status=%s price=%.8f filled=%.8f",
                execution.outcome,
                getattr(result, "status", None),
                getattr(result, "average_price", None) or 0.0,
                getattr(result, "filled_quantity", None) or 0.0,
            )

        if not execution.is_filled or result is None:
            logger.error(
                "[SELL FAILED] symbol=%s outcome=%s error=%s -- position "
                "remains OPEN, will be re-attempted on the next tick",
                position.symbol,
                execution.outcome,
                execution.error,
            )
            return

        exit_price = result.average_price

        if exit_price is None or exit_price <= 0:
            exit_price = fallback_price

        # docs/BUSINESS_RULES.md §8 Daily Loss Limit: computed from the
        # quantity/entry_price *before* close() runs, i.e. only the PnL
        # from whatever is being closed right now. Any earlier partial
        # scale-out's PnL (Sprint 3) was already recorded via
        # _record_realized_pnl at the time it happened, so re-reading
        # position.pnl after close() (which now includes that earlier
        # amount too) would double-count it.
        final_chunk_pnl = (exit_price - position.entry_price) * position.quantity

        self._position_manager.close(
            position.symbol,
            exit_price=exit_price,
            reason=reason,
            exchange=position.exchange,
        )

        self._record_realized_pnl(final_chunk_pnl)

        if self._trade_journal is not None:
            self._trade_journal.record_exit(
                position.symbol,
                exit_price=exit_price,
                reason=reason,
                pnl=getattr(position, "pnl", None),
                pnl_percent=getattr(position, "pnl_percent", None),
                exchange=position.exchange,
                commission=getattr(result, "fee_cost", None) if result else None,
            )

        if self._event_bus is not None:
            self._event_bus.publish(
                "position.closed",
                {
                    "symbol": position.symbol,
                    "exchange": position.exchange,
                    "reason": reason,
                    "price": exit_price,
                    "position": position,
                },
            )

    def check_break_even(self, position, ticker) -> None:
        # docs/BUSINESS_RULES.md §8: break-even and trailing activation
        # share a single 2.0% threshold -- they are one event, not two.
        activation = self._risk.trailing_activation_percent

        profit = (
            (ticker.last_price - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        if position.stop_price is None:
            position.stop_price = position.entry_price
            position.stop_stage = "BREAK_EVEN"
            logger.debug("[BREAK-EVEN] Activated for %s", position.symbol)
            return

        if position.stop_price < position.entry_price:
            position.stop_price = position.entry_price
            position.stop_stage = "BREAK_EVEN"
            logger.debug("[BREAK-EVEN] Updated for %s", position.symbol)

    def check_trailing(self, position, ticker) -> None:
        activation = self._risk.trailing_activation_percent

        profit = (
            (ticker.last_price - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        current_highest = getattr(position, "highest_price", None)

        if current_highest is None:
            current_highest = ticker.last_price

        highest_price = max(
            ticker.last_price,
            current_highest,
        )

        position.highest_price = highest_price

        trailing_stop = highest_price * (
            1 - self._risk.trailing_percent / 100
        )

        if (
            position.stop_price is None
            or trailing_stop > position.stop_price
        ):
            position.stop_price = trailing_stop
            position.stop_stage = "TRAILING"
            logger.debug("[TRAILING] Updated for %s to %.8f", position.symbol, trailing_stop)

from datetime import UTC, datetime

from app.core.exchange.market_key import market_key
from app.core.watch_list import WatchState


def _cfg(config):
    return getattr(config, "strategy", config)


def _coin_key(ticker) -> str:
    """Sprint 18: WatchList/PositionManager identity for this ticker."""
    return market_key(getattr(ticker, "exchange", None), ticker.symbol)


class Strategy:
    """
    Generates entry signals only.

    Per docs/BUSINESS_RULES.md #11 and docs/ARCHITECTURE.md, Strategy must
    never send exchange orders, manage positions or perform risk
    validation itself. Every candidate BUY signal is handed to
    RiskManager.open_position(), which owns trade-permission checks,
    position sizing, order validation, order submission and position
    registration. Strategy only reacts to the resulting Position (or None)
    to update WatchList bookkeeping.
    """

    _DEPENDENCY_NAMES = (
        "risk_manager",
        "position_manager",
        "trade_journal",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._risk_manager = None
        self._position_manager = None
        self._trade_journal = None
        self._config = None

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("Strategy is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def set_risk_manager(self, risk_manager) -> None:
        self._risk_manager = risk_manager

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def set_config(self, config) -> None:
        self._config = config

    def on_config_updated(self, event) -> None:
        """EventBus `config.updated` -- thresholds are read live from
        `self._config` on every tick; this hook exists so observers are
        wired and scan/log side-effects can be added later."""
        return None

    def on_ticker(
        self,
        watch_list,
        ticker,
    ) -> None:
        key = _coin_key(ticker)
        state = watch_list.get_state(key)

        if state is None:
            return

        if state in (
            WatchState.POSITION_OPEN,
            WatchState.BREAK_EVEN,
        ):
            self._handle_position_open(
                watch_list,
                ticker,
            )
            return

        if (
            self._position_manager is not None
            and self._position_manager.is_open(
                ticker.symbol,
                exchange=ticker.exchange,
            )
        ):
            return

        if state == WatchState.IDLE:
            self._handle_idle(watch_list, ticker)
            return

        if state == WatchState.WATCH_FALLING:
            self._handle_falling_watch(watch_list, ticker)
            return

        if state == WatchState.WATCH_RISING:
            self._handle_rising_watch(watch_list, ticker)

    def _handle_idle(self, watch_list, ticker) -> None:
        """
        docs/BUSINESS_RULES.md §2 defines two entry paths into the same
        strategy: Path A (price is already rising -- no prior dip) and
        Path B (price falls first, then reverses). Both must lead into
        WATCH_RISING with identical watch/entry parameters from then on;
        only how a coin *arrives* at WATCH_RISING differs.
        """
        key = _coin_key(ticker)
        watch_percent = _cfg(self._config).watch_percent

        if ticker.change_24h <= -watch_percent:
            # Path B: price is dropping -- start tracking the low first.
            watch_list.begin_falling_watch(
                key,
                ticker.last_price,
            )
            return

        if ticker.change_24h >= watch_percent:
            # Path A: price is already rising without ever dropping.
            # Enter WATCH_RISING directly, using the current price as the
            # reference point the further +entry_percent recovery is
            # measured from -- identical treatment to Path B once here.
            watch_list.begin_rising_watch(
                key,
                ticker.last_price,
            )

    def _handle_falling_watch(self, watch_list, ticker) -> None:
        key = _coin_key(ticker)
        watch_list.record_falling_price(
            key,
            ticker.last_price,
        )

        coin = watch_list.get(key)

        if ticker.last_price > coin["lowest_price"]:
            watch_list.begin_rising_watch(
                key,
                ticker.last_price,
            )

    def _handle_rising_watch(self, watch_list, ticker) -> None:
        key = _coin_key(ticker)
        watch_list.record_rising_price(
            key,
            ticker.last_price,
        )

        coin = watch_list.get(key)

        recovery = (
            (ticker.last_price - coin["lowest_price"])
            / coin["lowest_price"]
        ) * 100

        if recovery < _cfg(self._config).entry_percent:
            return

        watch_list.promote_to_buy_pending(
            key,
            ticker.last_price,
        )

        if self._risk_manager is None:
            watch_list.cancel_buy_pending(key)
            return

        # Strategy never talks to the exchange directly (BUSINESS_RULES.md
        # #12) and never carries its own copy of risk parameters (stop
        # loss %, position sizing caps all live on RiskManager). RiskManager
        # performs the balance check, dynamic/liquidity-based position
        # sizing, order validation, order submission and position
        # registration, and returns the resulting Position (or None if
        # rejected/unfilled). `volume_24h` is passed through so RiskManager
        # can cap the trade at 0.1% of the coin's own liquidity.
        position = self._risk_manager.open_position(
            exchange_type=ticker.exchange,
            symbol=ticker.symbol,
            price=ticker.last_price,
            volume_24h=ticker.volume_24h,
        )

        if position is None:
            watch_list.cancel_buy_pending(key)
            return

        watch_list.promote_to_position_open(
            key,
            position.entry_price,
            position.stop_price,
        )

        self._record_journal_entry(coin, ticker, position)

    def _record_journal_entry(self, coin, ticker, position) -> None:
        """Sprint 5 -- Trade Journal: only Strategy knows *why* this BUY
        happened (which entry path, how long it was watched, how many
        times price rose/fell while watching) -- that context lives on
        the WatchList coin dict fetched at the top of
        _handle_rising_watch, before promote_to_buy_pending/
        promote_to_position_open touched anything relevant to it."""
        if self._trade_journal is None:
            return

        watch_started_at = coin.get("watch_started_at")
        wait_minutes = None

        if watch_started_at is not None:
            wait_minutes = (
                datetime.now(UTC) - watch_started_at
            ).total_seconds() / 60.0

        exchange_name = getattr(ticker.exchange, "name", ticker.exchange)

        self._trade_journal.record_entry(
            symbol=ticker.symbol,
            exchange=exchange_name,
            entry_price=position.entry_price,
            quantity=position.quantity,
            entry_reason=coin.get("entry_path") or "PATH_B_DIP_RECOVERY",
            watch_started_at=watch_started_at,
            wait_minutes=wait_minutes,
            rise_events=coin.get("rise_count", 0),
            fall_events=coin.get("fall_count", 0),
        )

    def _handle_position_open(
        self,
        watch_list,
        ticker,
    ) -> None:
        if self._position_manager is None:
            return

        position = self._position_manager.get(
            ticker.symbol,
            exchange=ticker.exchange,
        )

        if position is None:
            return

        if ticker.last_price > position.entry_price:
            watch_list.update_highest_price(
                _coin_key(ticker),
                ticker.last_price,
            )

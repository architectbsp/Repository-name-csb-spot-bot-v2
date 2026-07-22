"""PaperExchangeAdapter -- local wallet fills with optional live prices."""

from app.core.exchange.adapter import PaperExchangeAdapter, RealExchangeAdapter
from app.core.exchange.models import ConnectionStatus, ExchangeState, ExchangeType


class _StubLive:
    """Minimal live venue stand-in for adapter tests."""

    def __init__(self) -> None:
        self.state = ExchangeState(exchange=ExchangeType.BINANCE, enabled=True)
        self.client = None
        self._tickers = {
            "BTC/USDT": {"last": 100.0, "close": 100.0, "quoteVolume": 1e6}
        }
        self._stream = object()

    def connect(self) -> None:
        self.state.status = ConnectionStatus.CONNECTED

    def disconnect(self) -> None:
        self.state.status = ConnectionStatus.DISCONNECTED

    def fetch_balance(self):
        return {"USDT": {"free": 999.0, "used": 0.0, "total": 999.0}}

    def fetch_markets(self):
        return {"BTC/USDT": {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT"}}

    def fetch_tickers(self):
        return self._tickers

    def fetch_my_trades(self, symbol=None, limit=None):
        return []

    def get_price_stream(self):
        return self._stream

    def get_market_metadata(self, symbol):
        from app.core.exchange.models import MarketMetadata

        return MarketMetadata(
            symbol=symbol,
            base="BTC",
            quote="USDT",
            price_precision=8,
            amount_precision=8,
            minimum_amount=1e-8,
            minimum_cost=1.0,
            active=True,
        )

    def normalize_amount(self, symbol, amount):
        return float(amount)

    def normalize_price(self, symbol, price):
        return float(price)

    def place_market_buy(self, symbol, amount):
        raise AssertionError("live place_market_buy must not be called")

    def place_market_sell(self, symbol, amount):
        raise AssertionError("live place_market_sell must not be called")

    def fetch_ohlcv(self, symbol, timeframe="15m", limit=200):
        return []

    def ping_ms(self):
        return 1.0


def test_paper_buy_and_sell_updates_local_wallet():
    paper = PaperExchangeAdapter(
        live=None,
        initial_quote=10_000.0,
        fee_rate=0.0,
    )
    paper.connect()
    paper.set_mark_price("BTC/USDT", 100.0)

    buy = paper.place_market_buy("BTC/USDT", 10.0)
    assert buy.status == "CLOSED"
    assert buy.filled_quantity == 10.0
    assert paper.fetch_quote_balance("USDT") == 9_000.0
    assert paper.fetch_base_balance("BTC") == 10.0

    paper.set_mark_price("BTC/USDT", 110.0)
    sell = paper.place_market_sell("BTC/USDT", 10.0)
    assert sell.status == "CLOSED"
    assert paper.fetch_base_balance("BTC") == 0.0
    assert paper.fetch_quote_balance("USDT") == 10_100.0


def test_paper_uses_live_stream_but_not_live_balance():
    live = _StubLive()
    paper = PaperExchangeAdapter(live, initial_quote=500.0)  # type: ignore[arg-type]
    paper.connect()

    assert paper.get_price_stream() is live._stream
    assert paper.fetch_quote_balance("USDT") == 500.0
    assert live.state.status == ConnectionStatus.CONNECTED


def test_real_adapter_delegates_to_live():
    live = _StubLive()
    real = RealExchangeAdapter(live)  # type: ignore[arg-type]
    real.connect()
    assert real.fetch_quote_balance("USDT") == 999.0
    assert real.get_price_stream() is live._stream

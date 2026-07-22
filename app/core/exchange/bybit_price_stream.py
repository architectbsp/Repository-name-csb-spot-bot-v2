from __future__ import annotations

from app.core.exchange.models import ExchangeType
from app.core.exchange.ws_price_stream_base import WebsocketPriceStreamBase
from app.core.market_data.models import NormalizedTicker


class BybitPriceStream(WebsocketPriceStreamBase):
    """
    Bybit v5 public spot "tickers" WebSocket stream.

    Docs: https://bybit-exchange.github.io/docs/v5/websocket/public/ticker
    """

    MAINNET_URL = "wss://stream.bybit.com/v5/public/spot"
    TESTNET_URL = "wss://stream-testnet.bybit.com/v5/public/spot"

    KEEPALIVE_INTERVAL_SECONDS = 20.0

    def __init__(self, *, testnet: bool = False) -> None:
        super().__init__()
        self._url_value = self.TESTNET_URL if testnet else self.MAINNET_URL

    @property
    def _url(self) -> str:
        return self._url_value

    def _to_wire_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def _subscribe_payload(self, wire_symbols: list[str]):
        return {
            "op": "subscribe",
            "args": [f"tickers.{symbol}" for symbol in wire_symbols],
        }

    def _unsubscribe_payload(self, wire_symbols: list[str]):
        return {
            "op": "unsubscribe",
            "args": [f"tickers.{symbol}" for symbol in wire_symbols],
        }

    def _keepalive_payload(self):
        return {"op": "ping"}

    def _parse_ticker(self, data: dict) -> NormalizedTicker | None:
        topic = data.get("topic", "")

        if not topic.startswith("tickers."):
            return None

        payload = data.get("data")

        if not payload:
            return None

        symbol = payload.get("symbol")
        last_price = payload.get("lastPrice")

        if not symbol or last_price is None:
            return None

        change_fraction = payload.get("price24hPcnt")
        quote_volume = payload.get("turnover24h")

        return NormalizedTicker(
            exchange=ExchangeType.BYBIT,
            symbol=self._usdt_pair_from_compact(symbol),
            last_price=float(last_price),
            volume_24h=float(quote_volume) if quote_volume is not None else 0.0,
            change_24h=(
                float(change_fraction) * 100
                if change_fraction is not None
                else 0.0
            ),
            timestamp=int(data.get("ts") or 0),
            raw_last_price=str(last_price),
        )

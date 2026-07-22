from __future__ import annotations

from app.core.exchange.models import ExchangeType
from app.core.exchange.ws_price_stream_base import WebsocketPriceStreamBase
from app.core.market_data.models import NormalizedTicker


class MEXCPriceStream(WebsocketPriceStreamBase):
    """
    MEXC spot v3 public "miniTicker" WebSocket stream.

    Docs: https://mexcdevelop.github.io/apidocs/spot_v3_en/#miniticker

    MEXC does not offer a public spot sandbox/testnet, so this always
    connects to the live public market-data feed regardless of the
    testnet setting.
    """

    URL = "wss://wbs.mexc.com/ws"

    KEEPALIVE_INTERVAL_SECONDS = 20.0

    def __init__(self, *, testnet: bool = False) -> None:
        super().__init__()
        self._testnet = testnet

    @property
    def _url(self) -> str:
        return self.URL

    def _to_wire_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def _channel(self, wire_symbol: str) -> str:
        return f"spot@public.miniTicker.v3.api@{wire_symbol}"

    def _subscribe_payload(self, wire_symbols: list[str]):
        return {
            "method": "SUBSCRIBE",
            "params": [self._channel(symbol) for symbol in wire_symbols],
        }

    def _unsubscribe_payload(self, wire_symbols: list[str]):
        return {
            "method": "UNSUBSCRIBE",
            "params": [self._channel(symbol) for symbol in wire_symbols],
        }

    def _keepalive_payload(self):
        return {"method": "PING"}

    def _parse_ticker(self, data: dict) -> NormalizedTicker | None:
        channel = data.get("c", "")

        if "miniTicker" not in channel:
            return None

        payload = data.get("d")

        if not payload:
            return None

        symbol = payload.get("s")
        price = payload.get("p")

        if not symbol or price is None:
            return None

        change_rate = payload.get("r")
        quote_volume = payload.get("tq")

        return NormalizedTicker(
            exchange=ExchangeType.MEXC,
            symbol=self._usdt_pair_from_compact(symbol),
            last_price=float(price),
            volume_24h=float(quote_volume) if quote_volume is not None else 0.0,
            change_24h=(
                float(change_rate) * 100 if change_rate is not None else 0.0
            ),
            timestamp=int(payload.get("t") or 0),
            raw_last_price=str(price),
        )

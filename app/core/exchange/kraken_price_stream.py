from __future__ import annotations

from app.core.exchange.models import ExchangeType
from app.core.exchange.ws_price_stream_base import WebsocketPriceStreamBase
from app.core.market_data.models import NormalizedTicker


class KrakenPriceStream(WebsocketPriceStreamBase):
    """
    Kraken WebSocket API v2 public "ticker" channel.

    Docs: https://docs.kraken.com/api/docs/websocket-v2/ticker

    Kraken has no public spot sandbox/testnet, so this always connects to
    the live public market-data feed regardless of the testnet setting
    (market data is not sandboxed; only authenticated trading is).
    """

    URL = "wss://ws.kraken.com/v2"

    def __init__(self, *, testnet: bool = False) -> None:
        super().__init__()
        self._testnet = testnet

    @property
    def _url(self) -> str:
        return self.URL

    def _to_wire_symbol(self, symbol: str) -> str:
        # Kraken v2 already uses the 'BTC/USDT' convention.
        return symbol.upper()

    def _subscribe_payload(self, wire_symbols: list[str]):
        return {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": wire_symbols,
            },
        }

    def _unsubscribe_payload(self, wire_symbols: list[str]):
        return {
            "method": "unsubscribe",
            "params": {
                "channel": "ticker",
                "symbol": wire_symbols,
            },
        }

    def _parse_ticker(self, data: dict) -> NormalizedTicker | None:
        if data.get("channel") != "ticker":
            return None

        payload_list = data.get("data")

        if not payload_list:
            return None

        payload = payload_list[0]

        symbol = payload.get("symbol")
        last = payload.get("last")

        if not symbol or last is None:
            return None

        last_price = float(last)
        volume = payload.get("volume")

        # Kraken v2 ticker reports base-asset volume only; approximate the
        # quote-asset (USD/USDT) volume used for volume filtering elsewhere
        # in the codebase by multiplying by the last traded price.
        quote_volume = float(volume) * last_price if volume is not None else 0.0

        change_pct = payload.get("change_pct")

        return NormalizedTicker(
            exchange=ExchangeType.KRAKEN,
            symbol=symbol.upper(),
            last_price=last_price,
            volume_24h=quote_volume,
            change_24h=float(change_pct) if change_pct is not None else 0.0,
            timestamp=0,
        )

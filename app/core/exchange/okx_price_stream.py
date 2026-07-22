from __future__ import annotations

from app.core.exchange.models import ExchangeType
from app.core.exchange.ws_price_stream_base import WebsocketPriceStreamBase
from app.core.market_data.models import NormalizedTicker


class OKXPriceStream(WebsocketPriceStreamBase):
    """
    OKX v5 public "tickers" WebSocket stream.

    Docs: https://www.okx.com/docs-v5/en/#public-data-websocket-tickers-channel

    OKX's public market-data channel is identical for live trading and
    demo ("paper") trading -- only private order/account endpoints differ
    -- so the same public endpoint is used regardless of testnet setting.
    """

    URL = "wss://ws.okx.com:8443/ws/v5/public"

    KEEPALIVE_INTERVAL_SECONDS = 20.0

    def __init__(self, *, testnet: bool = False) -> None:
        super().__init__()
        # OKX has no separate public market-data sandbox endpoint; ticker
        # data is identical between live and demo trading.
        self._testnet = testnet

    @property
    def _url(self) -> str:
        return self.URL

    def _to_wire_symbol(self, symbol: str) -> str:
        return symbol.replace("/", "-").upper()

    def _subscribe_payload(self, wire_symbols: list[str]):
        return {
            "op": "subscribe",
            "args": [
                {"channel": "tickers", "instId": symbol}
                for symbol in wire_symbols
            ],
        }

    def _unsubscribe_payload(self, wire_symbols: list[str]):
        return {
            "op": "unsubscribe",
            "args": [
                {"channel": "tickers", "instId": symbol}
                for symbol in wire_symbols
            ],
        }

    def _keepalive_payload(self):
        # OKX expects a literal "ping" text frame (not JSON) and replies
        # with a literal "pong".
        return "ping"

    def _parse_ticker(self, data: dict) -> NormalizedTicker | None:
        arg = data.get("arg") or {}

        if arg.get("channel") != "tickers":
            return None

        payload_list = data.get("data")

        if not payload_list:
            return None

        payload = payload_list[0]

        inst_id = payload.get("instId")
        last = payload.get("last")

        if not inst_id or last is None:
            return None

        last_price = float(last)
        change_24h = 0.0

        open_24h = payload.get("open24h")

        if open_24h:
            open_price = float(open_24h)

            if open_price > 0:
                change_24h = (last_price - open_price) / open_price * 100

        quote_volume = payload.get("volCcy24h")

        return NormalizedTicker(
            exchange=ExchangeType.OKX,
            symbol=self._pair_from_dashed(inst_id),
            last_price=last_price,
            volume_24h=float(quote_volume) if quote_volume else 0.0,
            change_24h=change_24h,
            timestamp=int(payload.get("ts") or 0),
            raw_last_price=str(last),
        )

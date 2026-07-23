"""
Sprint 12 -- TelemetryService unit tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.services.telemetry_service import TelemetryService


class DummyExchangeManager:
    def ping_ms(self, exchange_type=None):
        return 42.5


class DummyScanner:
    def last_scan_elapsed_ms(self):
        return 321.0


def test_telemetry_records_order_latency_average():
    tel = TelemetryService()
    tel.record_order_latency(100.0)
    tel.record_order_latency(200.0)

    snap = tel.collect()
    assert snap.order_latency_ms == 150.0


def test_telemetry_data_age_from_ticker_timestamps():
    tel = TelemetryService()
    # 2 seconds old (ms epoch).
    now_s = 1_700_000_000.0
    tickers = {
        "BINANCE:BTC/USDT": SimpleNamespace(
            timestamp=int((now_s - 2.0) * 1000)
        ),
        "BINANCE:ETH/USDT": SimpleNamespace(
            timestamp=int((now_s - 0.5) * 1000)
        ),
    }
    snap = tel.collect(tickers=tickers, now_seconds=now_s)
    assert snap.data_age_seconds is not None
    assert abs(snap.data_age_seconds - 2.0) < 0.05


def test_telemetry_loop_time_from_scanner_and_event():
    tel = TelemetryService()
    tel.set_market_scanner(DummyScanner())
    snap = tel.collect()
    assert snap.loop_time_ms == 321.0

    tel.on_scan_completed({"elapsed_ms": 450.0})
    snap2 = tel.collect()
    assert snap2.loop_time_ms == 450.0


def test_telemetry_pipeline_and_api_ping_and_system():
    tel = TelemetryService()
    tel.set_exchange_manager(DummyExchangeManager())
    tel.record_pipeline_ms(88.0)

    # Force ping (no throttle cache).
    snap = tel.collect()
    assert snap.pipeline_ms == 88.0
    assert snap.api_latency_ms == 42.5
    assert snap.ram_mb is not None and snap.ram_mb > 0
    # CPU may be 0 on first sample (no prior delta).
    assert snap.cpu_percent is not None


def test_telemetry_maps_into_dashboard_snapshot_fields():
    from datetime import UTC, datetime

    from app.core.services.dashboard_service import DashboardService

    class DummyScanner:
        def last_scan_result(self):
            return []

        def last_scan_elapsed_ms(self):
            return 111.0

    class DummyExchangeManager:
        def enabled_exchange_types(self):
            return []

        def enabled(self):
            return []

        def ping_ms(self, exchange_type=None):
            return 55.0

    service = DashboardService()
    tel = TelemetryService()
    tel.record_order_latency(120.0)
    tel.record_pipeline_ms(33.0)
    service.set_telemetry(tel)
    service.set_exchange_manager(DummyExchangeManager())
    service.set_market_scanner(DummyScanner())
    tel.set_exchange_manager(DummyExchangeManager())
    tel.set_market_scanner(DummyScanner())

    # Seed a fresh ticker so data age is computable.
    from app.core.exchange.models import ExchangeType
    from app.core.market_data.models import NormalizedTicker
    import time

    now_ms = int(time.time() * 1000)
    service.on_ticker_updated(
        NormalizedTicker(
            exchange=ExchangeType.BINANCE,
            symbol="BTC/USDT",
            last_price=1.0,
            volume_24h=1.0,
            change_24h=0.0,
            timestamp=now_ms - 1500,
        )
    )

    snap = service.build_snapshot()
    assert isinstance(snap.generated_at, datetime)
    assert snap.generated_at.tzinfo == UTC
    assert snap.order_latency_ms == 120.0
    assert snap.pipeline_ms == 33.0
    assert snap.scan_elapsed_ms == 111.0
    assert snap.api_latency_ms == 55.0
    assert snap.data_age_seconds is not None
    assert snap.data_age_seconds >= 1.0
    assert snap.ram_mb is not None
    assert snap.pending_order_count == 0
    assert snap.watchlist_count == 0

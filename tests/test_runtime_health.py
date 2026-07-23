"""R7 -- runtime health snapshot aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.exchange.models import ConnectionStatus, ExchangeState, ExchangeType
from app.core.scheduler.job import Job
from app.core.scheduler.scheduler import Scheduler
from app.core.services.runtime_health import RuntimeHealthService
from app.core.worker import Worker


class _FakeExchange:
    def __init__(self, status: ConnectionStatus, *, ws_running: bool = False):
        self.state = ExchangeState(
            exchange=ExchangeType.BINANCE,
            status=status,
            enabled=True,
            last_error=None,
        )
        self._ws_running = ws_running

    def get_price_stream(self):
        return SimpleNamespace(running=self._ws_running, connected=self._ws_running)


class _FakeExchangeManager:
    def __init__(self, exchanges):
        self._exchanges = exchanges

    def enabled(self):
        return list(self._exchanges)


class _FakeOES:
    def __init__(self, quarantined=None, active=None):
        self._quarantined = list(quarantined or [])
        self._active = list(active or [])

    def list_quarantined(self):
        return list(self._quarantined)

    def list_active_client_orders(self):
        return list(self._active)


class _FakeRisk:
    def __init__(self, oes):
        self.order_execution = oes


class _FakeTelemetry:
    def __init__(self, **kwargs):
        self._kwargs = kwargs

    def collect(self):
        return SimpleNamespace(
            order_latency_ms=self._kwargs.get("order_latency_ms"),
            data_age_seconds=self._kwargs.get("data_age_seconds", 1.0),
            loop_time_ms=None,
            pipeline_ms=None,
            api_latency_ms=self._kwargs.get("api_latency_ms"),
            ram_mb=10.0,
            cpu_percent=1.0,
        )


class _FakePersistence:
    @property
    def engine(self):
        from app.core.persistence.database import get_engine

        return get_engine()


def _engine(**kwargs):
    scheduler = Scheduler()
    scheduler.start()
    job = Job(name="probe", interval=1, callback=lambda: None)
    job.next_run = datetime.now() - timedelta(seconds=10)
    scheduler.register(job)
    scheduler.schedule(job)
    # force overdue: next_run in the past beyond 2*interval
    job.next_run = datetime.now() - timedelta(seconds=5)

    worker = Worker(scheduler)
    worker._active = True
    worker._thread = SimpleNamespace(is_alive=lambda: True)
    worker._last_tick_at = datetime.now()

    oes = _FakeOES(
        quarantined=kwargs.get("quarantined"),
        active=kwargs.get("active"),
    )
    return SimpleNamespace(
        running=kwargs.get("running", True),
        runtime_health={},
        worker=worker,
        scheduler=scheduler,
        exchange=_FakeExchangeManager(
            [
                _FakeExchange(
                    kwargs.get("status", ConnectionStatus.CONNECTED),
                    ws_running=kwargs.get("ws_running", True),
                )
            ]
        ),
        risk_manager=_FakeRisk(oes),
        telemetry=_FakeTelemetry(
            data_age_seconds=kwargs.get("data_age_seconds", 1.0),
            order_latency_ms=kwargs.get("order_latency_ms", 12.0),
        ),
        persistence=_FakePersistence(),
        event_bus=SimpleNamespace(
            stats=lambda: {
                "publish_count": 3,
                "handler_errors": 0,
                "topic_count": 2,
            }
        ),
    )


def test_health_snapshot_healthy(tmp_path, monkeypatch):
    from app.core.persistence import database as dbmod

    dbmod.configure_database(f"sqlite:///{tmp_path / 'h.db'}")
    svc = RuntimeHealthService()
    engine = _engine()
    # Avoid delayed job by setting next_run in future
    for job in engine.scheduler.jobs.values():
        job.next_run = datetime.now() + timedelta(seconds=30)
    svc.set_engine(engine)
    snap = svc.snapshot()
    assert snap["alive"] is True
    assert snap["degraded"] is False
    assert snap["worker"]["ok"] is True
    assert snap["exchanges"]["any_connected"] is True
    assert snap["persistence"]["ok"] is True
    assert "signature=" not in str(snap)


def test_health_snapshot_detects_exchange_disconnect(tmp_path):
    from app.core.persistence import database as dbmod

    dbmod.configure_database(f"sqlite:///{tmp_path / 'h2.db'}")
    svc = RuntimeHealthService()
    engine = _engine(status=ConnectionStatus.DISCONNECTED, ws_running=False)
    for job in engine.scheduler.jobs.values():
        job.next_run = datetime.now() + timedelta(seconds=30)
    svc.set_engine(engine)
    snap = svc.snapshot()
    assert snap["degraded"] is True
    assert "exchange_disconnected" in snap["issues"]


def test_health_snapshot_detects_scheduler_delay(tmp_path):
    from app.core.persistence import database as dbmod

    dbmod.configure_database(f"sqlite:///{tmp_path / 'h3.db'}")
    svc = RuntimeHealthService()
    engine = _engine()
    # leave next_run overdue from fixture
    svc.set_engine(engine)
    snap = svc.snapshot()
    assert snap["degraded"] is True
    assert "scheduler_jobs_delayed" in snap["issues"]


def test_health_snapshot_recovery_attention_without_unresolved(tmp_path):
    from app.core.persistence import database as dbmod

    dbmod.configure_database(f"sqlite:///{tmp_path / 'h4.db'}")
    svc = RuntimeHealthService()
    engine = _engine(quarantined=["BINANCE:BTCUSDT"])
    for job in engine.scheduler.jobs.values():
        job.next_run = datetime.now() + timedelta(seconds=30)
    svc.set_engine(engine)
    snap = svc.snapshot()
    assert snap["recovery"]["attention"] is True
    assert "recovery_unresolved" not in snap["issues"]


def test_health_snapshot_redacts_errors(tmp_path):
    from app.core.persistence import database as dbmod

    dbmod.configure_database(f"sqlite:///{tmp_path / 'h5.db'}")
    svc = RuntimeHealthService()
    engine = _engine()
    for job in engine.scheduler.jobs.values():
        job.next_run = datetime.now() + timedelta(seconds=30)
        job.last_error = "NetworkError signature=abc123 apiKey=SECRET"
    svc.set_engine(engine)
    snap = svc.snapshot()
    blob = str(snap)
    assert "SECRET" not in blob
    assert "abc123" not in blob

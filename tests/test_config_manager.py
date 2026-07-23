"""
ConfigManager singleton + ConfigUpdatedEvent: Settings Kaydet must
mutate live AppSettings and notify Strategy / Scanner / RiskManager
observers without a restart.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config.config_manager import (
    CONFIG_UPDATED_EVENT,
    PARAM_ALIASES,
    ConfigManager,
    ConfigUpdatedEvent,
    schema_covers_prompt_params,
)
from app.core.config.settings import AppSettings
from app.core.config.settings_store import SettingsStore
from app.core.event_bus.event_bus import EventBus
from app.core.market_scanner import MarketScanner
from app.core.persistence.database import Base
from app.core.persistence.repository import SettingsRepository
from app.core.scheduler.scheduler import Scheduler


def make_store() -> SettingsStore:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, future=True)()
    return SettingsStore(SettingsRepository(session))


def setup_manager(tmp_path=None):
    ConfigManager.reset_instance()
    store = make_store()
    settings = AppSettings()
    store.load_into(settings)
    bus = EventBus()
    manager = ConfigManager.instance()
    kwargs = {}
    if tmp_path is not None:
        kwargs["json_path"] = tmp_path / "config.json"
    manager.configure(settings, store, bus, **kwargs)
    return manager, settings, bus


def test_prompt_aliases_all_map_into_settings_schema():
    covered = schema_covers_prompt_params()
    assert set(covered) == set(PARAM_ALIASES)
    assert covered["watch_pct"] == "watch_percent"
    assert covered["break_even"] == "trailing_activation_percent"
    assert covered["capital_pct"] == "max_balance_utilization_percent"
    assert covered["take_profit_activation"] == "partial_tp_activation_percent"


def test_save_publishes_config_updated_event():
    manager, settings, bus = setup_manager()
    received: list[ConfigUpdatedEvent] = []
    bus.subscribe(CONFIG_UPDATED_EVENT, received.append)

    errors = manager.save(
        {"watch_pct": 3.5, "max_daily_loss": 15.0},
        source="settings_ui",
    )

    assert errors == []
    assert settings.strategy.watch_percent == 3.5
    assert settings.risk.max_daily_loss_percent == 15.0
    assert len(received) == 1
    assert isinstance(received[0], ConfigUpdatedEvent)
    assert received[0].source == "settings_ui"
    assert "watch_percent" in received[0].changed
    assert "max_daily_loss_percent" in received[0].changed


def test_scanner_updates_job_interval_on_config_updated():
    manager, settings, bus = setup_manager()
    scheduler = Scheduler()
    scanner = MarketScanner()
    scanner.set_config(settings)
    scanner.set_scheduler(scheduler)
    scanner.initialize()

    bus.subscribe(CONFIG_UPDATED_EVENT, scanner.on_config_updated)

    job = scheduler.get("market_scanner")
    assert job is not None
    assert job.interval == settings.strategy.scan_interval_seconds

    manager.save({"scan_interval": 42})
    assert job.interval == 42.0


def test_config_json_mirror_when_path_configured(tmp_path):
    manager, settings, bus = setup_manager(tmp_path=tmp_path)
    path = tmp_path / "config.json"

    manager.save({"entry_pct": 8.0})

    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "entry_percent" in text
    assert "8.0" in text or "8" in text


def test_singleton_reset_for_tests():
    ConfigManager.reset_instance()
    a = ConfigManager.instance()
    b = ConfigManager.instance()
    assert a is b
    ConfigManager.reset_instance()
    c = ConfigManager.instance()
    assert c is not a


def test_settings_service_alias_is_config_manager():
    from app.core.config import SettingsService

    assert SettingsService is ConfigManager


def test_risk_and_position_manager_pick_up_live_config_without_restart():
    from app.core.position_manager import PositionManager
    from app.core.risk_manager import RiskManager
    from app.core.domain.position import Position
    from datetime import UTC, datetime

    manager, settings, bus = setup_manager()
    pm = PositionManager()
    pm.set_config(settings)
    rm = RiskManager()
    rm.set_config(settings)
    rm.set_position_manager(pm)

    bus.subscribe(CONFIG_UPDATED_EVENT, pm.on_config_updated)
    bus.subscribe(CONFIG_UPDATED_EVENT, rm.on_config_updated)

    manager.save({"max_position": 1, "stop_loss": 7.5})
    assert settings.risk.max_open_positions == 1
    assert settings.risk.stop_loss_percent == 7.5
    assert rm._risk.stop_loss_percent == 7.5

    assert pm.add(
        Position(
            symbol="AAA/USDT",
            entry_price=1.0,
            quantity=1.0,
            opened_at=datetime.now(UTC),
            stop_price=0.9,
        )
    )
    assert (
        pm.add(
            Position(
                symbol="BBB/USDT",
                entry_price=1.0,
                quantity=1.0,
                opened_at=datetime.now(UTC),
                stop_price=0.9,
            )
        )
        is False
    )


def test_multi_strategy_pipeline_applies_config_updated_to_deepcopy():
    from app.core.strategies.orchestrator import MultiStrategyOrchestrator
    from app.core.exchange.adapter import PaperExchangeAdapter
    from app.core.exchange.manager import ExchangeManager
    from app.core.exchange.models import ExchangeType
    from app.core.exchange.registry import ExchangeRegistry

    manager, settings, bus = setup_manager()
    paper = PaperExchangeAdapter(
        live=None,
        exchange_type=ExchangeType.BINANCE,
        initial_quote=100_000.0,
        fee_rate=0.0,
    )
    paper.connect()
    registry = ExchangeRegistry()
    registry.register(ExchangeType.BINANCE, paper)
    exchange = ExchangeManager(registry)

    orch = MultiStrategyOrchestrator()
    pipelines = orch.build(
        exchange,
        base_config=settings,
        strategy_names=["dip_hunter", "momentum"],
    )
    bus.subscribe(CONFIG_UPDATED_EVENT, orch.on_config_updated)

    # Momentum starts with preset watch=3.0; Settings save must update it.
    assert pipelines[1].config.strategy.watch_percent == 3.0
    assert pipelines[1].config is not settings

    manager.save({"watch_pct": 4.25, "stop_loss": 12.0})

    assert pipelines[0].config.strategy.watch_percent == 4.25
    assert pipelines[1].config.strategy.watch_percent == 4.25
    assert pipelines[0].config.risk.stop_loss_percent == 12.0
    assert pipelines[1].config.risk.stop_loss_percent == 12.0
    # Momentum preset max_open_positions=5 stays until Settings changes it.
    assert pipelines[1].config.risk.max_open_positions == 5

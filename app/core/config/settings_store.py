"""
Bridges the persisted settings row (SQLite, via SettingsRepository) and
the live, shared AppSettings instance that Strategy, WatchList,
RiskManager and MarketScanner all hold a reference to.

docs/BUSINESS_RULES.md: no strategy/risk parameter may be hardcoded in
source. SETTINGS_SCHEMA is the single declarative list of every
user-editable knob; it drives the Settings UI form, validation, and the
DB <-> AppSettings mapping in both directions.

Runtime reload (no restart required): `update()`/`load_into()` mutate the
*same* AppSettings instance's nested dataclasses in place rather than
replacing it with a new object. Every module reads `self._config.risk.x`
/ `self._config.strategy.x` fresh on each access (there is no local
caching anywhere in Strategy/WatchList/RiskManager/MarketScanner), so a
saved change is visible starting with the very next tick or scan -- no
restart, no extra wiring per module required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config.settings import AppSettings
from app.core.persistence.models import SettingsEntity
from app.core.persistence.repository import SettingsRepository


@dataclass(frozen=True, slots=True)
class SettingField:
    section: str  # "risk" or "strategy" -- attribute name on AppSettings
    name: str  # attribute name on the section dataclass
    label: str  # human-readable label for the Settings UI
    value_type: type
    minimum: float
    maximum: float
    unit: str = "%"
    # For str fields, ``maximum`` is max length (0 = unlimited).


# NOTE on two parameters from the original wishlist that intentionally do
# NOT get their own separate field:
#   - "break even": break-even activation and trailing activation are the
#     same event by design (docs/BUSINESS_RULES.md §8) -- both are driven
#     by trailing_activation_percent below, so there is exactly one knob
#     and it can never drift out of sync with itself.
#   - "capital %": replaced by dynamic liquidity-based sizing (§8); the
#     knobs that now control position sizing are
#     max_balance_utilization_percent, max_volume_share_percent and the
#     Sprint 8 advanced sizing fields (risk_per_trade / ATR / volatility).
#   - "take profit activation": there is no separate fixed take-profit
#     target -- profit is realized via the trailing stop reversal, whose
#     activation is trailing_activation_percent.
SETTINGS_SCHEMA: tuple[SettingField, ...] = (
    SettingField("strategy", "watch_percent", "İzleme Eşiği (Watch %)", float, 0.1, 50.0),
    SettingField("strategy", "entry_percent", "Giriş Eşiği (Entry %)", float, 0.1, 50.0),
    SettingField("strategy", "min_volume_usd", "Min. 24s Hacim", float, 0.0, 1_000_000_000.0, unit="USD"),
    SettingField("strategy", "max_position_hours", "Maks. Pozisyon Süresi", int, 1, 24 * 30, unit="saat"),
    SettingField("strategy", "scan_interval_seconds", "Tarama Aralığı", int, 5, 3600, unit="sn"),
    SettingField(
        "strategy",
        "trading_hours_enabled",
        "Çalışma Saatleri (0=Kapalı 1=Aktif)",
        int,
        0,
        1,
        unit="",
    ),
    SettingField(
        "strategy",
        "weekend_closed",
        "Hafta Sonu Kapalı (0=Hayır 1=Evet)",
        int,
        0,
        1,
        unit="",
    ),
    SettingField(
        "strategy",
        "quiet_start_hour_utc",
        "Pasif Başlangıç Saati (UTC)",
        int,
        0,
        23,
        unit="saat",
    ),
    SettingField(
        "strategy",
        "quiet_end_hour_utc",
        "Pasif Bitiş Saati (UTC)",
        int,
        0,
        23,
        unit="saat",
    ),
    SettingField(
        "strategy",
        "blacklist_symbols",
        "Kara Liste Sembolleri (virgülle)",
        str,
        0,
        4000,
        unit="",
    ),
    SettingField(
        "strategy",
        "filtered_patterns",
        "Sembol Regex Filtreleri (virgülle)",
        str,
        0,
        4000,
        unit="",
    ),
    SettingField("risk", "stop_loss_percent", "Sabit Stop (Hard Stop)", float, 0.1, 90.0),
    SettingField("risk", "trailing_activation_percent", "Trailing / Break-Even Aktivasyonu", float, 0.1, 90.0),
    SettingField("risk", "trailing_percent", "Trailing Mesafesi (Callback Rate)", float, 0.1, 90.0),
    SettingField("risk", "cooldown_hours", "Cooldown Süresi", float, 0.0, 24 * 14, unit="saat"),
    SettingField("risk", "max_open_positions", "Maks. Açık Pozisyon", int, 1, 200, unit="adet"),
    SettingField("risk", "max_daily_loss_percent", "Günlük Maks. Zarar Limiti", float, 1.0, 100.0),
    SettingField("risk", "max_balance_utilization_percent", "Maks. Bakiye Kullanımı", float, 1.0, 100.0),
    SettingField("risk", "max_volume_share_percent", "Maks. 24s Hacim Payı", float, 0.001, 100.0),
    SettingField(
        "risk",
        "position_sizing_mode",
        "Pozisyon Boyutu (0=Likidite 1=Hibrit 2=FixedRisk 3=ATR 4=Dynamic/Kelly 5=Fixed%)",
        int,
        0,
        5,
        unit="",
    ),
    SettingField(
        "risk",
        "risk_per_trade_percent",
        "İşlem Başına Risk / Fixed% (Fixed Risk / ATR / Fixed%)",
        float,
        0.1,
        20.0,
    ),
    SettingField("risk", "atr_period", "ATR Periyodu", int, 2, 100, unit="mum"),
    SettingField("risk", "atr_multiplier", "ATR Stop Çarpanı", float, 0.5, 10.0, unit="x"),
    SettingField(
        "risk",
        "volatility_target_percent",
        "Hedef Volatilite (0 = kapalı)",
        float,
        0.0,
        50.0,
    ),
    SettingField(
        "risk",
        "volatility_lookback",
        "Volatilite Lookback",
        int,
        5,
        200,
        unit="mum",
    ),
    SettingField(
        "risk",
        "kelly_fraction",
        "Kelly Çarpanı (0.5 = Half-Kelly)",
        float,
        0.05,
        1.0,
        unit="x",
    ),
    SettingField(
        "risk",
        "kelly_min_trades",
        "Kelly Min. Kapalı İşlem",
        int,
        5,
        500,
        unit="adet",
    ),
    SettingField(
        "risk",
        "dynamic_lookback_trades",
        "Dynamic/Kelly Lookback (0 = tümü)",
        int,
        0,
        500,
        unit="adet",
    ),
    SettingField("risk", "partial_tp_activation_percent", "Kısmi Kar Alma Eşiği (0 = kapalı)", float, 0.0, 90.0),
    SettingField("risk", "partial_tp_sell_percent", "Kısmi Kar Alma Satış Oranı", float, 1.0, 99.0),
)

_SCHEMA_BY_NAME: dict[str, SettingField] = {field.name: field for field in SETTINGS_SCHEMA}


def apply_schema_values(app_settings: AppSettings, values: dict[str, object]) -> None:
    """
    Mutates ``app_settings`` in place with schema-named values (no persist).

    Used by multi-strategy pipelines that hold a deep-copied AppSettings:
    when ConfigManager publishes ``config.updated``, each pipeline applies
    ``event.changed`` here so Settings UI edits become live without restart.
    Unknown keys are ignored.
    """
    for name, raw_value in values.items():
        field = _SCHEMA_BY_NAME.get(name)
        if field is None:
            continue
        section = getattr(app_settings, field.section)
        if field.value_type is str:
            setattr(section, name, str(raw_value if raw_value is not None else ""))
        else:
            setattr(section, name, field.value_type(raw_value))


class SettingsStore:
    def __init__(self, repository: SettingsRepository) -> None:
        self._repository = repository

    def load_into(self, app_settings: AppSettings) -> None:
        """
        Applies persisted values (if any) onto `app_settings` in place.
        On the very first run (no row yet), persists the compiled-in
        defaults so the Settings screen and future updates have a
        baseline row.
        """
        entity = self._repository.load()

        if entity is None:
            self._persist(app_settings)
            return

        for field in SETTINGS_SCHEMA:
            section = getattr(app_settings, field.section)
            raw = getattr(entity, field.name)
            if field.value_type is str:
                setattr(section, field.name, str(raw if raw is not None else ""))
            else:
                setattr(section, field.name, field.value_type(raw))

    def current_values(self, app_settings: AppSettings) -> dict[str, object]:
        return {
            field.name: getattr(getattr(app_settings, field.section), field.name)
            for field in SETTINGS_SCHEMA
        }

    def update(self, app_settings: AppSettings, changes: dict[str, object]) -> list[str]:
        """
        Validates `changes` (field name -> new raw value, e.g. from UI
        text fields) and, only if every value is valid, applies all of
        them at once onto the live `app_settings` instance and persists
        the result. Returns a list of human-readable validation error
        messages; an empty list means the update succeeded. Unknown
        field names are ignored rather than rejected, so callers can pass
        a whole form's worth of fields without special-casing extras.
        """
        errors: list[str] = []
        validated: dict[str, object] = {}

        for name, raw_value in changes.items():
            field = _SCHEMA_BY_NAME.get(name)

            if field is None:
                continue

            if name == "position_sizing_mode":
                from app.core.risk_manager import resolve_position_sizing_mode

                try:
                    raw_value = resolve_position_sizing_mode(raw_value)
                except ValueError:
                    errors.append(
                        f"{field.label}: geçersiz değer ('{raw_value}')"
                    )
                    continue

            if field.value_type is str:
                value = str(raw_value if raw_value is not None else "")
                max_len = int(field.maximum)
                if max_len > 0 and len(value) > max_len:
                    errors.append(
                        f"{field.label}: en fazla {max_len} karakter olmalı"
                    )
                    continue
                validated[name] = value
                continue

            try:
                value = field.value_type(raw_value)
            except (TypeError, ValueError):
                errors.append(f"{field.label}: geçersiz değer ('{raw_value}')")
                continue

            if not (field.minimum <= value <= field.maximum):
                errors.append(
                    f"{field.label}: {field.minimum}-{field.maximum} aralığında olmalı"
                )
                continue

            validated[name] = value

        if errors:
            return errors

        for name, value in validated.items():
            field = _SCHEMA_BY_NAME[name]
            section = getattr(app_settings, field.section)
            setattr(section, name, value)

        self._persist(app_settings)
        return []

    def _persist(self, app_settings: AppSettings) -> None:
        values = self.current_values(app_settings)

        entity = SettingsEntity(
            id=1,
            updated_at=datetime.now(UTC),
            **values,
        )
        self._repository.save(entity)

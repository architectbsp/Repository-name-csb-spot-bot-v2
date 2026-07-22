import flet as ft

from app.core.domain.dashboard import DashboardSnapshot
from app.ui.formatting import signed_money, signed_percent


def _card(title, value, subtitle, color):
    return ft.Container(
        expand=True,
        height=95,
        bgcolor="#0B1220",
        border_radius=14,
        padding=16,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column(
                    spacing=3,
                    controls=[
                        ft.Text(title, size=11, color="#64748B"),
                        ft.Text(
                            value,
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color=color,
                        ),
                        ft.Text(subtitle, size=11, color="#94A3B8"),
                    ],
                ),
                ft.Container(
                    width=42,
                    height=42,
                    border_radius=21,
                    bgcolor="#111827",
                    content=ft.Text("●", color=color, size=16),
                ),
            ],
        ),
    )


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f} ms"


def _fmt_mb(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f} MB"


def _fmt_cpu(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}%"


def build_dashboard_cards(snapshot: DashboardSnapshot | None = None):
    if snapshot is None:
        total_pnl = "-"
        total_color = "#94A3B8"
        daily = "-"
        daily_color = "#94A3B8"
        positions = "0"
        signals = "0"
        scan = "-"
        latency = "-"
        ram = "-"
        cpu = "-"
        hours = "AKTİF"
        hours_color = "#22C55E"
    else:
        total_pnl = signed_money(snapshot.total_pnl)
        total_color = (
            "#22C55E"
            if (snapshot.total_pnl or 0) >= 0
            else "#EF4444"
        )
        daily_usd = signed_money(snapshot.daily_realized_pnl)
        daily_pct = signed_percent(snapshot.daily_pnl_percent)
        daily = f"{daily_usd} ({daily_pct})"
        daily_color = (
            "#22C55E"
            if (snapshot.daily_realized_pnl or 0) >= 0
            else "#EF4444"
        )
        positions = f"{snapshot.open_position_count:02d}"
        signals = str(snapshot.active_signal_count)
        scan = _fmt_ms(snapshot.scan_elapsed_ms)
        latency = _fmt_ms(snapshot.api_latency_ms)
        ram = _fmt_mb(snapshot.ram_mb)
        cpu = _fmt_cpu(snapshot.cpu_percent)
        if snapshot.trading_hours_active:
            hours = "AKTİF"
            hours_color = "#22C55E"
        else:
            hours = "PASİF"
            hours_color = "#F59E0B"

    row1 = ft.Row(
        spacing=15,
        controls=[
            _card("TOTAL PNL", total_pnl, "All-time realized", total_color),
            _card("DAILY PNL", daily, "Today (UTC)", daily_color),
            _card("POSITIONS", positions, "Open Trades", "#3B82F6"),
            _card("WATCH / PENDING", signals, "Active Signals", "#F59E0B"),
        ],
    )
    row2 = ft.Row(
        spacing=15,
        controls=[
            _card("SCAN", scan, "Volume scan duration", "#38BDF8"),
            _card("API LATENCY", latency, "Exchange REST ping", "#A855F7"),
            _card("RAM", ram, "Bot process RSS", "#94A3B8"),
            _card("CPU", cpu, "Bot process", "#94A3B8"),
            _card("TRADING HOURS", hours, "New entries", hours_color),
        ],
    )
    return ft.Column(spacing=12, controls=[row1, row2])

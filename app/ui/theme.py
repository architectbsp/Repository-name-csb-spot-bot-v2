import flet as ft

# ---------- COLORS ----------

BG = "#0B1120"
SURFACE = "#111827"
CARD = "#1A2332"
BORDER = "#273449"

PRIMARY = "#3B82F6"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"

TEXT = "#F8FAFC"
TEXT_SECONDARY = "#94A3B8"

# ---------- PAGE ----------

def setup_page(page: ft.Page):
    page.title = "CSB Spot Bot v2"

    page.bgcolor = BG

    page.theme_mode = ft.ThemeMode.DARK

    page.padding = 15

    page.spacing = 15

    page.window_width = 1700
    page.window_height = 950

    page.window_min_width = 1400
    page.window_min_height = 800

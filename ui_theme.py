"""Bitcoin Miner Studio UI theme preset registry."""
from __future__ import annotations

DEFAULT_UI_THEME = "purple"

UI_THEME_PRESETS = {
    "purple": "Purple",
    "graphite": "Graphite",
    "obsidian": "Obsidian",
    "frost": "Frost",
    "sapphire": "Sapphire",
    "crimson": "Crimson",
    "emerald": "Emerald",
    "cyan": "Cyan",
    "amber": "Amber",
    "rose": "Rose",
}


def normalize_ui_theme(value) -> str:
    key = str(value or "").strip().lower()
    return key if key in UI_THEME_PRESETS else DEFAULT_UI_THEME


def ui_theme_options() -> list[dict[str, str]]:
    return [{"id": key, "name": name} for key, name in UI_THEME_PRESETS.items()]

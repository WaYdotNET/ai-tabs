"""The dark and light themes: which one the restore screen uses, and switching between them."""

import asyncio
from datetime import datetime

import pytest
from factories import windows_with_tabs

from ai_tabs import config, palette, store
from ai_tabs.tui import RestoreApp


def test_auto_follows_a_dark_macos_appearance(monkeypatch):
    monkeypatch.setattr(palette, "system_is_dark", lambda: True)

    assert palette.chosen_palette() is palette.DARK


def test_auto_follows_a_light_macos_appearance(monkeypatch):
    monkeypatch.setattr(palette, "system_is_dark", lambda: False)

    assert palette.chosen_palette() is palette.LIGHT


def test_the_theme_setting_wins_over_the_macos_appearance(monkeypatch):
    monkeypatch.setattr(palette, "system_is_dark", lambda: True)
    config.write_config({"theme": "light"})

    assert palette.chosen_palette() is palette.LIGHT


def test_an_unknown_theme_is_refused():
    with pytest.raises(ValueError, match="theme must be auto, dark or light, not 'blue'"):
        config.parse_setting("theme", "blue")


def test_t_switches_the_restore_screen_to_the_other_theme():
    config.write_config({"theme": "dark"})
    store.insert_snapshot(windows_with_tabs(2), {"opened": [], "closed": [], "changed": []},
                          datetime(2026, 11, 3, 10, 0, 0))
    app = RestoreApp(None, open_tabs=True)
    themes = []

    async def drive() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            themes.append(app.theme)
            await pilot.press("t")
            await pilot.pause()
            themes.append(app.theme)

    asyncio.run(drive())

    assert themes == ["ai-tabs-dark", "ai-tabs-light"]

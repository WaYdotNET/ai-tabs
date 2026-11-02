"""The terminal around the restore screen: when the splash shows, and the font of the session."""

from ai_tabs import config
from ai_tabs.screen import current_session_id, font_with_size, splash_allowed

ITERM = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:CF724064-2C11-4EBA-95AF-E9300CC7DEA8"}


def test_font_size_changes_and_the_font_name_stays():
    assert font_with_size("JetBrainsMono-Regular 25", 16) == "JetBrainsMono-Regular 16"


def test_font_name_with_spaces_keeps_all_its_words():
    assert font_with_size("Fira Code Retina 13", 11) == "Fira Code Retina 11"


def test_session_id_is_the_part_after_the_position():
    assert current_session_id(ITERM) == "CF724064-2C11-4EBA-95AF-E9300CC7DEA8"


def test_splash_shows_in_an_iterm2_terminal_by_default():
    assert splash_allowed(ITERM, is_terminal=True) is True


def test_no_splash_when_the_output_is_not_a_terminal():
    assert splash_allowed(ITERM, is_terminal=False) is False


def test_no_splash_outside_iterm2():
    assert splash_allowed({"TERM_PROGRAM": "Apple_Terminal"}, is_terminal=True) is False


def test_no_splash_when_the_setting_is_off():
    config.write_config({"splash": False})

    assert splash_allowed(ITERM, is_terminal=True) is False


def test_tui_font_size_is_empty_by_default_and_takes_a_number():
    before = config.settings().tui_font_size
    config.write_config({"tui_font_size": config.parse_setting("tui_font_size", "16")})

    assert (before, config.settings().tui_font_size) == (None, 16)

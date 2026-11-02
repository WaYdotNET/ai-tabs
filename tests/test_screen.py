"""When the splash with the logo shows."""

from ai_tabs import config
from ai_tabs.screen import splash_allowed

ITERM = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t0p0:CF724064-2C11-4EBA-95AF-E9300CC7DEA8"}


def test_splash_shows_in_an_iterm2_terminal_by_default():
    assert splash_allowed(ITERM, is_terminal=True) is True


def test_no_splash_when_the_output_is_not_a_terminal():
    assert splash_allowed(ITERM, is_terminal=False) is False


def test_no_splash_outside_iterm2():
    assert splash_allowed({"TERM_PROGRAM": "Apple_Terminal"}, is_terminal=True) is False


def test_no_splash_when_the_setting_is_off():
    config.write_config({"splash": False})

    assert splash_allowed(ITERM, is_terminal=True) is False

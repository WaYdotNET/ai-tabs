"""The colors of ai-tabs: a dark and a light palette, both from the colors of the logo."""

from dataclasses import dataclass

from .config import settings
from .system import run

DEFAULTS = "/usr/bin/defaults"


@dataclass(frozen=True)
class Palette:
    """The colors of one theme. `cursor` is the background of the highlighted entry."""

    name: str
    dark: bool
    cyan: str
    purple: str
    green: str
    gold: str
    red: str
    foreground: str
    muted: str
    background: str
    surface: str
    panel: str
    cursor: str


# Sampled from assets/logo.png. The purple is lighter than the logo purple, which is too dark
# to read on navy.
DARK = Palette(name="ai-tabs-dark", dark=True, cyan="#01EAFC", purple="#AE72F5", green="#52FA74",
               gold="#FCB60D", red="#FF6464", foreground="#FBFBFC", muted="#7187A6", background="#010A2D",
               surface="#081637", panel="#092852", cursor="#023468")

# The logo colors made darker where they are hard to read on white. The purple and the green
# are the logo purple and the shadow of the logo green.
LIGHT = Palette(name="ai-tabs-light", dark=False, cyan="#0086A8", purple="#5025B0", green="#028441",
                gold="#A86F00", red="#C62828", foreground="#081637", muted="#5A6B85", background="#F5F8FD",
                surface="#FFFFFF", panel="#E3ECF8", cursor="#CFE6FB")

PALETTES = {"dark": DARK, "light": LIGHT}


def system_is_dark() -> bool:
    """Tell if macOS uses the dark appearance. `defaults` fails when the appearance is light."""
    return run(DEFAULTS, "read", "-g", "AppleInterfaceStyle").strip() == "Dark"


def chosen_palette() -> Palette:
    """Return the palette of the `theme` setting. `auto` follows the macOS appearance."""
    theme = settings().theme
    if theme in PALETTES:
        return PALETTES[theme]
    return DARK if system_is_dark() else LIGHT


def other_palette(current: Palette) -> Palette:
    """Return the light palette for the dark one, and the dark palette for the light one."""
    return LIGHT if current.dark else DARK

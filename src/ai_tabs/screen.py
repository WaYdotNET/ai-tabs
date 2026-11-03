"""The splash with the logo, before the restore screen opens."""

import base64
import os
import shutil
import sys
import time
from importlib.resources import files

from .config import settings

SPLASH_WIDTH = 36
SPLASH_SECONDS = 1.2
# The logo is 480 × 320 pixels, and a terminal cell is about twice as high as it is wide.
SPLASH_HEIGHT = SPLASH_WIDTH * 320 // 480 // 2


def in_iterm(environment: dict[str, str]) -> bool:
    """Tell if the process runs in an iTerm2 session."""
    return environment.get("TERM_PROGRAM") == "iTerm.app" and bool(environment.get("ITERM_SESSION_ID"))


def splash_allowed(environment: dict[str, str], is_terminal: bool) -> bool:
    """Tell if the splash can show: `splash` is on, and the output is an iTerm2 terminal."""
    return settings().splash and is_terminal and in_iterm(environment)


def inline_image(data: bytes, width: int) -> str:
    """Return the iTerm2 escape sequence that shows a PNG `width` cells wide."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"\033]1337;File=inline=1;size={len(data)};width={width};preserveAspectRatio=1:{encoded}\a"


def show_splash() -> None:
    """Show the logo in the middle of the terminal for a moment, before the restore screen opens.

    The logo goes to the alternate screen, so it does not stay in the scrollback. The font and
    the size of the terminal do not change.
    """
    if not splash_allowed(dict(os.environ), sys.stdout.isatty()):
        return
    columns, rows = shutil.get_terminal_size()
    row = max(1, (rows - SPLASH_HEIGHT) // 2)
    column = max(1, (columns - SPLASH_WIDTH) // 2)
    data = files("ai_tabs").joinpath("assets/logo.png").read_bytes()
    sys.stdout.write(f"\033[?1049h\033[2J\033[?25l\033[{row};{column}H{inline_image(data, SPLASH_WIDTH)}")
    sys.stdout.flush()
    time.sleep(SPLASH_SECONDS)
    # iTerm2 keeps an inline image when other text covers its cells. Leaving the alternate screen
    # discards it, so the restore screen does not show it through its own text.
    sys.stdout.write("\033[2J\033[?1049l\033[?25h")
    sys.stdout.flush()

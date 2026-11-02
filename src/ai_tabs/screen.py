"""The terminal around the restore screen: the splash with the logo, and the text size."""

import base64
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.resources import files

import iterm2

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

    The logo goes to the alternate screen, so it does not stay in the scrollback: the restore
    screen clears it, and the terminal goes back to the normal screen when it closes.
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
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def font_with_size(font: str, size: int) -> str:
    """Return an iTerm2 font description (`Name Size`) with another size."""
    name, _, _ = font.rpartition(" ")
    return f"{name} {size}"


def current_session_id(environment: dict[str, str]) -> str:
    """Return the iTerm2 session ID of this process. `ITERM_SESSION_ID` is `w0t0p0:ID`."""
    return environment.get("ITERM_SESSION_ID", "").partition(":")[2]


def set_session_font(session_id: str, new_font: Callable[[str], str]) -> str | None:
    """Give the session the font that `new_font` returns for its current font.

    Return the font of the session before the change, or None when the session is not found.
    """

    async def change(connection: iterm2.Connection) -> str | None:
        app = await iterm2.async_get_app(connection)
        session = app.get_session_by_id(session_id)
        if session is None:
            return None
        before = (await session.async_get_profile()).normal_font
        update = iterm2.LocalWriteOnlyProfile()
        update.set_normal_font(new_font(before))
        await session.async_set_profile_properties(update)
        return before

    return iterm2.run_until_complete(change)


@contextmanager
def text_size() -> Iterator[None]:
    """Use `tui_font_size` for the text of this iTerm2 session while the block runs.

    The session gets its font back at the end, also after an error. Without `tui_font_size`,
    or outside iTerm2, nothing changes.
    """
    size = settings().tui_font_size
    environment = dict(os.environ)
    if size is None or not in_iterm(environment):
        yield
        return
    session_id = current_session_id(environment)
    before = set_session_font(session_id, lambda font: font_with_size(font, size))
    try:
        yield
    finally:
        if before:
            set_session_font(session_id, lambda _: before)

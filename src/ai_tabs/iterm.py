"""Read the windows, tabs and panes of iTerm2 through its Python API."""

import re

import iterm2

from .agents import find_agent
from .config import OSASCRIPT
from .models import Pane, Tab, Window
from .system import run

STATUS_PREFIX_RE = re.compile(r"^π\s*[>\u2800-\u28ff]?\s*")


def iterm_is_running() -> bool:
    """Tell if iTerm2 runs. The check does not start iTerm2."""
    answer = run(OSASCRIPT, "-e", 'application "iTerm2" is running')
    return answer.strip() == "true"


def without_status(text: str) -> str:
    """Remove the omp status prefix (`π >` when idle, `π` and a spinner when busy).

    The prefix changes with the agent state, so it would make every snapshot differ.
    """
    return STATUS_PREFIX_RE.sub("", text.strip())


async def read_pane(session: iterm2.Session) -> Pane:
    """Read one iTerm2 session and the agent that runs in it."""
    tty = await session.async_get_variable("tty") or ""
    path = await session.async_get_variable("path") or ""
    return Pane(without_status(session.name or ""), tty, path, find_agent(tty))


def shown_tab_color(profile: iterm2.Profile, dark_mode: bool) -> iterm2.Color | None:
    """Return the tab color that iTerm2 shows for a profile, or None.

    If the profile uses separate colors for light and dark mode, iTerm2 shows only the color
    of the current mode, and ignores the plain tab color.
    """
    if not profile.use_separate_colors_for_light_and_dark_mode:
        return profile.tab_color if profile.use_tab_color else None
    if dark_mode:
        return profile.tab_color_dark if profile.use_tab_color_dark else None
    return profile.tab_color_light if profile.use_tab_color_light else None


async def tab_color(session: iterm2.Session, dark_mode: bool) -> list[int] | None:
    """Return the tab color that the session shows, as RGB, or None if it shows no color."""
    color = shown_tab_color(await session.async_get_profile(), dark_mode)
    return [round(color.red), round(color.green), round(color.blue)] if color else None


async def read_tab(tab: iterm2.Tab, dark_mode: bool) -> Tab:
    """Read the title, the color and the panes of one tab."""
    title = await tab.async_get_variable("titleOverride") or ""
    color = await tab_color(tab.sessions[0], dark_mode)
    panes = [await read_pane(session) for session in tab.sessions]
    return Tab(title, color, panes)


async def read_window(window: iterm2.Window, dark_mode: bool) -> Window:
    """Read the frame and the tabs of one window."""
    frame = await window.async_get_frame()
    box = [frame.origin.x, frame.origin.y, frame.size.width, frame.size.height]
    return Window(box, [await read_tab(tab, dark_mode) for tab in window.tabs])


async def read_windows(connection: iterm2.Connection) -> list[Window]:
    """Read all iTerm2 windows, in their current order."""
    app = await iterm2.async_get_app(connection)
    theme = await app.async_get_variable("effectiveTheme") or ""
    dark_mode = "dark" in theme.split()
    return [await read_window(window, dark_mode) for window in app.terminal_windows]

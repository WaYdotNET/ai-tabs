"""Read the windows, tabs and panes of iTerm2 through its Python API."""

import itertools
import re
from collections.abc import Iterator
from typing import Any

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


def split_tree(node: Any, pane_numbers: Iterator[int]) -> dict:
    """Return the layout dict of a split tree node.

    A node with `children` is a splitter. Any other node is a pane, and takes the next number
    from `pane_numbers`. The tree is walked depth first, the order of `iterm2.Tab.sessions`.
    """
    if not hasattr(node, "children"):
        return {"pane": next(pane_numbers)}
    return {"vertical": node.vertical, "children": [split_tree(child, pane_numbers) for child in node.children]}


def layout_tree(root: Any) -> dict | None:
    """Return the layout of a tab from its root splitter, or None if the tab has one pane.

    The root can be an `iterm2.Splitter` or any object with `vertical` and `children`.
    """
    pane_numbers = itertools.count()
    tree = split_tree(root, pane_numbers)
    has_splits = next(pane_numbers) > 1
    return tree if has_splits else None


async def read_pane(session: iterm2.Session, profile: iterm2.Profile) -> Pane:
    """Read one iTerm2 session, its profile name, its size and the agent that runs in it."""
    tty = await session.async_get_variable("tty") or ""
    path = await session.async_get_variable("path") or ""
    size = session.grid_size
    columns, rows = (size.width, size.height) if size else (None, None)
    return Pane(without_status(session.name or ""), tty, path, find_agent(tty), profile.name, columns, rows)


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


def tab_color(profile: iterm2.Profile, dark_mode: bool) -> list[int] | None:
    """Return the tab color that the profile shows, as RGB, or None if it shows no color."""
    color = shown_tab_color(profile, dark_mode)
    return [round(color.red), round(color.green), round(color.blue)] if color else None


async def read_tab(tab: iterm2.Tab, dark_mode: bool) -> Tab:
    """Read the title, the color, the panes and the split layout of one tab.

    The color comes from the profile of the first pane.
    """
    title = await tab.async_get_variable("titleOverride") or ""
    sessions = tab.sessions
    profiles = [await session.async_get_profile() for session in sessions]
    panes = [await read_pane(session, profile) for session, profile in zip(sessions, profiles, strict=True)]
    return Tab(title, tab_color(profiles[0], dark_mode), panes, layout_tree(tab.root))


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

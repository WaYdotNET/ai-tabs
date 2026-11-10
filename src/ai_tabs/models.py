"""The snapshot data: windows, tabs, panes and the agent sessions that run in them."""

import json
from dataclasses import asdict, dataclass, field, replace


@dataclass
class Agent:
    """An omp or Claude Code session and the command that resumes it.

    `argv` is the command line of the agent process, as `ps` shows it.
    """

    kind: str
    pid: int
    cwd: str
    session_id: str
    title: str
    resume: str
    argv: list[str] = field(default_factory=list)


@dataclass
class Pane:
    """One iTerm2 session: a pane inside a tab.

    `profile` is the name of the iTerm2 profile of the pane. `columns` and `rows` are the size
    of the pane in characters. They are None in snapshots from before they were saved.
    """

    name: str
    tty: str
    path: str
    agent: Agent | None = None
    profile: str | None = None
    columns: int | None = None
    rows: int | None = None


@dataclass
class Tab:
    """One iTerm2 tab. `color` is an RGB list, or None when the tab has no color.

    `layout` is the split tree of the panes. A node is `{"vertical": bool, "children": [...]}`
    and a leaf is `{"pane": index}`, an index into `panes`. None means that the tab has one
    pane, or that the snapshot is from before the layout was saved.
    """

    title: str
    color: list[int] | None
    panes: list[Pane] = field(default_factory=list)
    layout: dict | None = None


@dataclass
class Window:
    """One iTerm2 window. `frame` is [x, y, width, height]."""

    frame: list[float]
    tabs: list[Tab] = field(default_factory=list)


def positioned_tabs(windows: list[Window]) -> list[tuple[str, Tab]]:
    """Return every tab with its position, as `WINDOW.TAB` counted from 1."""
    return [(f"{w}.{t}", tab) for w, window in enumerate(windows, 1) for t, tab in enumerate(window.tabs, 1)]


def tab_count(windows: list[Window]) -> int:
    """Return the number of tabs in all the windows."""
    return sum(len(window.tabs) for window in windows)


def agent_count(windows: list[Window]) -> int:
    """Return the number of panes that run an agent session."""
    return sum(1 for _, tab in positioned_tabs(windows) for pane in tab.panes if pane.agent)


def without_pane_sizes(tab: Tab) -> Tab:
    """Return a copy of the tab with no size on its panes."""
    panes = [replace(pane, columns=None, rows=None) for pane in tab.panes]
    return replace(tab, panes=panes)


def without_sizes(window: Window) -> Window:
    """Return a copy of the window with no frame and no pane sizes.

    A resize of a window also changes the size of each pane in it.
    """
    tabs = [without_pane_sizes(tab) for tab in window.tabs]
    return replace(window, frame=[], tabs=tabs)


def differ_only_in_sizes(old: list[Window], new: list[Window]) -> bool:
    """Return True when the windows are the same except for window frames and pane sizes."""
    return [without_sizes(window) for window in old] == [without_sizes(window) for window in new]


def pane_from_data(raw: dict) -> Pane:
    """Build a Pane from snapshot data. Keys that older snapshots lack take their defaults."""
    agent = Agent(**raw["agent"]) if raw.get("agent") else None
    return Pane(**{**raw, "agent": agent})


def windows_from_data(raw_windows: list[dict]) -> list[Window]:
    """Build Window objects from snapshot data."""
    windows = []
    for raw_window in raw_windows:
        tabs = [Tab(raw_tab["title"], raw_tab["color"], [pane_from_data(raw) for raw in raw_tab["panes"]],
                    raw_tab.get("layout"))
                for raw_tab in raw_window["tabs"]]
        windows.append(Window(raw_window["frame"], tabs))
    return windows


def windows_to_json(windows: list[Window]) -> str:
    """Return the windows as compact JSON text, the format of the database."""
    return json.dumps([asdict(window) for window in windows], ensure_ascii=False, separators=(",", ":"))


def windows_from_json(text: str) -> list[Window]:
    """Build Window objects from the JSON text of the database."""
    return windows_from_data(json.loads(text))

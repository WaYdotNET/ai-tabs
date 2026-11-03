"""Choose what restore opens: the tabs, and the command that each pane runs."""

import copy
import shlex
from collections.abc import Iterator
from dataclasses import replace

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.text import Text

from . import agents
from .agents import is_still_running
from .display import FoldedLine, console, tab_heading
from .models import Pane, Tab, Window, positioned_tabs


def pane_command(pane: Pane) -> str:
    """Return the command that brings the pane back.

    If the agent session still runs in another tab, the command only opens its folder:
    two processes on the same session file would corrupt it.
    """
    agent = pane.agent
    if agent is None:
        return f"cd {shlex.quote(pane.path)}"
    if is_still_running(agent):
        return f"cd {shlex.quote(agent.cwd)}  # {agent.kind} session {agent.session_id} still runs"
    return agent.resume


def fresh_pane_commands(panes: list[Pane]) -> list[str]:
    """Return the command of each pane, from a new check of the running agent sessions.

    The restore screen checks the sessions when it opens. A session can stop after that, for
    example when its old tab closes, and then it must resume.
    """
    agents.running_sessions.cache_clear()
    return [pane_command(pane) for pane in panes]


def duplicate_agent(pane: Pane, first_position: str) -> Pane:
    """Return a copy of the pane whose agent only opens its folder, because a pane before it has the session."""
    agent = pane.agent
    note = f"cd {shlex.quote(agent.cwd)}  # {agent.kind} session {agent.session_id} is also in tab {first_position}"
    return replace(pane, agent=replace(agent, resume=note))


def first_places(windows: list[Window]) -> dict[tuple[str, str], tuple[str, int]]:
    """Return where each agent session first appears: its tab position and its pane index."""
    first: dict[tuple[str, str], tuple[str, int]] = {}
    for position, tab in positioned_tabs(windows):
        for index, pane in enumerate(tab.panes):
            if pane.agent:
                first.setdefault((pane.agent.kind, pane.agent.session_id), (position, index))
    return first


def resolve_duplicates(windows: list[Window]) -> list[Window]:
    """Return copies of the windows where only the first pane of each agent session resumes it.

    Two processes on the same session file would corrupt it. Later panes with the same kind
    and session ID only open the folder.
    """
    copies = copy.deepcopy(windows)
    first = first_places(copies)
    for position, tab in positioned_tabs(copies):
        tab.panes = [resolve_pane(pane, (position, index), first) for index, pane in enumerate(tab.panes)]
    return copies


def resolve_pane(pane: Pane, place: tuple[str, int], first: dict[tuple[str, str], tuple[str, int]]) -> Pane:
    """Return the pane, or its duplicate form when its session first appears in another place."""
    if pane.agent is None:
        return pane
    first_place = first[(pane.agent.kind, pane.agent.session_id)]
    return pane if first_place == place else duplicate_agent(pane, first_place[0])


def tab_is_running(tab: Tab) -> bool:
    """Tell if an agent of the tab still runs."""
    return any(pane.agent and is_still_running(pane.agent) for pane in tab.panes)


def default_positions(windows: list[Window]) -> list[str]:
    """Return the tabs that start selected: the ones without a running agent."""
    return [position for position, tab in positioned_tabs(windows) if not tab_is_running(tab)]


def keep_positions(windows: list[Window], positions: list[str]) -> list[Window]:
    """Keep only the selected tabs. Windows without a selected tab disappear."""
    kept = []
    for w_index, window in enumerate(windows, 1):
        tabs = [tab for t_index, tab in enumerate(window.tabs, 1) if f"{w_index}.{t_index}" in positions]
        if tabs:
            kept.append(Window(window.frame, tabs))
    return kept


def planned_tabs(windows: list[Window], positions: list[str]) -> Iterator[tuple[str, str, list[str]]]:
    """Yield the heading, the position and the pane commands of each selected tab, in snapshot order."""
    for position, tab in positioned_tabs(windows):
        if position in positions:
            yield tab_heading(tab), position, [pane_command(pane) for pane in tab.panes]


def plan_text(windows: list[Window], positions: list[str]) -> Text:
    """Return the commands that restore runs for the selected tabs, grouped by tab and with a
    blank line between the tabs. The commands stay whole, for a copy from the terminal."""
    lines = []
    for heading, position, commands in planned_tabs(windows, positions):
        lines.append(f"[bold]{escape(heading)}[/bold]  [dim]{position}[/dim]")
        lines += [f"  {escape(command)}" for command in commands] + [""]
    return Text.from_markup("\n".join(lines).rstrip("\n"))


def plan_view(windows: list[Window], positions: list[str]) -> Group:
    """Return the commands of the selected tabs for a window of the restore screen. A long command
    breaks at the width of the window and keeps its indent."""
    parts: list[RenderableType] = []
    for heading, position, commands in planned_tabs(windows, positions):
        parts.append(Text.from_markup(f"[bold]{escape(heading)}[/bold]  [dim]{position}[/dim]"))
        parts += [FoldedLine(command, 2) for command in commands] + [Text("")]
    return Group(*parts[:-1])


def print_plan(windows: list[Window], positions: list[str]) -> None:
    """Print what restore would open, with the positions of the snapshot, without opening anything."""
    console.print(plan_text(windows, positions), soft_wrap=True)

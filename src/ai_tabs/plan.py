"""Choose what restore opens: the tabs, and the command that each pane runs."""

import shlex

from rich.markup import escape
from rich.text import Text

from .agents import is_still_running
from .display import console, tab_heading
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


def plan_text(windows: list[Window], positions: list[str]) -> Text:
    """Return the commands that restore runs for the selected tabs, grouped by tab and with a
    blank line between the tabs."""
    lines = []
    for position, tab in positioned_tabs(windows):
        if position in positions:
            lines.append(f"[bold]{escape(tab_heading(tab))}[/bold]  [dim]{position}[/dim]")
            lines += [f"  {escape(pane_command(pane))}" for pane in tab.panes] + [""]
    return Text.from_markup("\n".join(lines).rstrip("\n"))


def print_plan(windows: list[Window], positions: list[str]) -> None:
    """Print what restore would open, with the positions of the snapshot, without opening anything."""
    console.print(plan_text(windows, positions), soft_wrap=True)

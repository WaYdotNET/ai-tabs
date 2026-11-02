"""The short text views of snapshots, tabs and sessions, shared by `show` and the restore screen."""

from rich.console import Console
from rich.markup import escape

from .agents import is_still_running
from .config import HOME
from .models import Pane, Tab, positioned_tabs
from .store import PIN_LABELS, Snapshot, Summary

console = Console()


def snapshot_markup(summary: Summary, newest: bool) -> str:
    """Return the lines that the snapshot list shows for one snapshot, as Rich markup.

    The third line shows only for a pinned snapshot, or when panes opened or closed: a crash
    shows as many closed panes.
    """
    latest = "  [cyan]latest[/cyan]" if newest else ""
    lines = [f"[bold]{summary.created_at:%H:%M:%S}[/bold]  [dim]{summary.created_at:%m-%d}[/dim]{latest}",
             f"[dim]{summary.tabs} tabs · {summary.agents} agents[/dim]"]
    notes = []
    if summary.pinned:
        notes.append(f"[magenta]📌 {PIN_LABELS.get(summary.pinned, summary.pinned)}[/magenta]")
    if summary.opened or summary.closed:
        notes.append(f"[yellow]+{summary.opened} −{summary.closed}[/yellow]")
    if notes:
        lines.append(" · ".join(notes))
    return "\n".join(lines)


def short_path(path: str) -> str:
    """Return a folder with the home folder as `~`, so that it takes less space."""
    home = str(HOME)
    return "~" + path[len(home):] if path.startswith(home) else path


def color_mark(color: list[int] | None) -> str:
    """Return a bar in the tab color, or a blank of the same width when the tab has no color."""
    if not color:
        return " "
    red, green, blue = color
    return f"[rgb({red},{green},{blue})]▌[/]"


def tab_heading(tab: Tab) -> str:
    """Return the name that the lists show for a tab: its own title, else the title of its
    first agent session, else the name of its first pane."""
    titles = [pane.agent.title for pane in tab.panes if pane.agent and pane.agent.title]
    return tab.title or next(iter(titles), tab.panes[0].name)


def pane_lines(pane: Pane, heading: str) -> list[str]:
    """Return the lines of one pane, as Rich markup.

    The session title shows only when it differs from the tab heading. Then come the agent and
    the folder. A green dot marks an agent session that still runs.
    """
    agent = pane.agent
    if agent is None:
        return [f"[dim]  shell · {escape(short_path(pane.path))}[/dim]"]
    state = "[green]●[/green]" if is_still_running(agent) else " "
    detail = f"{state} [dim]{agent.kind} · {escape(short_path(agent.cwd))}[/dim]"
    title = [f"  {escape(agent.title)}"] if agent.title and agent.title != heading else []
    return title + [detail]


def tab_markup(position: str, tab: Tab) -> str:
    """Return the tab heading and the lines of its panes, as Rich markup."""
    heading = tab_heading(tab)
    lines = [f"{color_mark(tab.color)} [bold]{escape(heading)}[/bold]  [dim]{position}[/dim]"]
    lines += [line for pane in tab.panes for line in pane_lines(pane, heading)]
    return "\n".join(lines)


def tab_matches(tab: Tab, query: str) -> bool:
    """Tell if every word of the query is in the tab title, a session title or a folder."""
    agents = [pane.agent for pane in tab.panes if pane.agent]
    fields = [tab.title, *(pane.name for pane in tab.panes), *(pane.path for pane in tab.panes),
              *(agent.title for agent in agents), *(agent.cwd for agent in agents)]
    text = " ".join(fields).lower()
    return all(word in text for word in query.lower().split())


def print_sessions(snapshot: Snapshot) -> None:
    """Print every tab of a snapshot as a short list: the tab heading, then the session of each pane."""
    summary = snapshot.summary
    pin = f" · 📌 {PIN_LABELS.get(summary.pinned, summary.pinned)}" if summary.pinned else ""
    console.print(f"[bold]Snapshot {summary.id}[/bold] · {summary.tabs} tabs · {summary.agents} agents{pin}"
                  "   [green]●[/green] still runs\n")
    for position, tab in positioned_tabs(snapshot.windows):
        console.print(tab_markup(position, tab) + "\n", highlight=False)

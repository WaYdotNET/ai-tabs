"""The short text views of snapshots, tabs and sessions, shared by `show` and the restore screen."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from rich.cells import chop_cells
from rich.console import Console, ConsoleOptions
from rich.markup import escape
from rich.text import Text

from .agents import is_still_running
from .config import HOME
from .models import Agent, Pane, Tab, positioned_tabs
from .palette import Palette
from .store import PIN_LABELS, Snapshot, Summary

if TYPE_CHECKING:
    from .history import Entry, Variant

console = Console()


@dataclass(frozen=True)
class FoldedLine:
    """A line of text that breaks at the width of its box, not at its spaces, with an indent on each part.

    Rich breaks text at spaces, which puts `cd` and a long folder on two lines.
    """

    text: str
    indent: int

    def __rich_console__(self, _console: Console, options: ConsoleOptions) -> Iterator[Text]:
        """Yield the parts of the line, each one as wide as the box allows."""
        width = max(options.max_width - self.indent, 1)
        for part in chop_cells(self.text, width):
            yield Text(" " * self.indent + part)


def snapshot_markup(summary: Summary, newest: bool, colors: Palette) -> str:
    """Return the lines that the snapshot list shows for one snapshot, as Rich markup.

    The third line shows only for a pinned snapshot, or when panes opened or closed: a crash
    shows as many closed panes.
    """
    latest = f"  [{colors.cyan}]latest[/]" if newest else ""
    lines = [f"[bold]{summary.created_at:%H:%M:%S}[/bold]  [dim]{summary.created_at:%m-%d}[/dim]{latest}",
             f"[dim]{summary.tabs} tabs · {summary.agents} agents[/dim]"]
    notes = []
    if summary.pinned:
        notes.append(f"[{colors.purple}]📌 {PIN_LABELS.get(summary.pinned, summary.pinned)}[/]")
    if summary.opened or summary.closed:
        notes.append(f"[{colors.gold}]+{summary.opened} −{summary.closed}[/]")
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


def pane_lines(pane: Pane, heading: str, colors: Palette) -> list[str]:
    """Return the lines of one pane, as Rich markup.

    The session title shows only when it differs from the tab heading. Then come the agent and
    the folder. A green dot marks an agent session that still runs.
    """
    agent = pane.agent
    if agent is None:
        return [f"[dim]  shell · {escape(short_path(pane.path))}[/dim]"]
    state = f"[{colors.green}]●[/]" if is_still_running(agent) else " "
    detail = f"{state} [dim]{agent.kind} · {escape(short_path(agent.cwd))}[/dim]"
    title = [f"  {escape(agent.title)}"] if agent.title and agent.title != heading else []
    return title + [detail]


def tab_markup(position: str, tab: Tab, colors: Palette) -> str:
    """Return the tab heading and the lines of its panes, as Rich markup."""
    heading = tab_heading(tab)
    lines = [f"{color_mark(tab.color)} [bold]{escape(heading)}[/bold]  [dim]{position}[/dim]"]
    lines += [line for pane in tab.panes for line in pane_lines(pane, heading, colors)]
    return "\n".join(lines)


def tab_matches(tab: Tab, query: str) -> bool:
    """Tell if every word of the query is in the tab title, a session title or a folder."""
    agents = [pane.agent for pane in tab.panes if pane.agent]
    fields = [tab.title, *(pane.name for pane in tab.panes), *(pane.path for pane in tab.panes),
              *(agent.title for agent in agents), *(agent.cwd for agent in agents)]
    text = " ".join(fields).lower()
    return all(word in text for word in query.lower().split())


def period(first: datetime, last: datetime) -> str:
    """Return a period as `MM-DD HH:MM → HH:MM`, with the end date too when it differs from the start."""
    start = f"{first:%m-%d %H:%M}"
    end = f"{last:%H:%M}" if first.date() == last.date() else f"{last:%m-%d %H:%M}"
    return f"{start} → {end}"


def counted_snapshots(count: int) -> str:
    """Return the count of snapshots with the right word: `1 snapshot` or `N snapshots`."""
    return "1 snapshot" if count == 1 else f"{count} snapshots"


def matched_tabs(count: int) -> str:
    """Return the count of matching tabs with the right words: `1 tab matches` or `N tabs match`."""
    return "1 tab matches" if count == 1 else f"{count} tabs match"


def _word_spans(lower_text: str, word: str) -> list[tuple[int, int]]:
    """Return every match span of one word in a lower-case text."""
    spans = []
    start = 0
    while (index := lower_text.find(word, start)) != -1:
        spans.append((index, index + len(word)))
        start = index + 1
    return spans


def _merged_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or touching spans, in order."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def highlight(text: str, query: str, color: str) -> str:
    """Return the text as escaped Rich markup, with every match of a query word highlighted."""
    words = [word for word in query.lower().split() if word]
    spans = _merged_spans([span for word in words for span in _word_spans(text.lower(), word)])
    pieces = []
    cursor = 0
    for start, end in spans:
        pieces.append(escape(text[cursor:start]))
        pieces.append(f"[bold underline {color}]{escape(text[start:end])}[/]")
        cursor = end
    pieces.append(escape(text[cursor:]))
    return "".join(pieces)


def _first_agent(tab: Tab) -> Agent:
    """Return the agent of the tab's first agent pane."""
    return next(pane.agent for pane in tab.panes if pane.agent)


def _kind_markup(tab: Tab, colors: Palette) -> str:
    """Return the kind on the right of an entry's heading: the agent kind, or shell."""
    agents = [pane.agent for pane in tab.panes if pane.agent]
    if not agents:
        return f"[{colors.muted}]shell[/]"
    dot = f"[{colors.green}]●[/] " if is_still_running(agents[0]) else ""
    return f"{dot}[{colors.green}]{agents[0].kind}[/]"


def _entry_heading_line(entry: Entry, query: str, colors: Palette) -> str:
    """Return the entry's first line: the color bar, the heading in bold, and the kind."""
    tab = entry.newest.tab
    heading = highlight(tab_heading(tab), query, colors.gold)
    return f"{color_mark(tab.color)} [bold]{heading}[/bold]  {_kind_markup(tab, colors)}"


def _agent_titles_line(entry: Entry, query: str, colors: Palette) -> str:
    """Return the agent entry's second line: the newest title, then the distinct older ones."""
    newest_title = _first_agent(entry.newest.tab).title
    older = [variant.text[1] for variant in entry.variants[1:]]
    distinct_older = [title for title in dict.fromkeys(older) if title != newest_title]
    line = f"    {highlight(newest_title, query, colors.gold)}"
    if distinct_older:
        joined = ", ".join(highlight(title, query, colors.gold) for title in distinct_older)
        line += f"   was: {joined}"
    return line


def _shell_names(entry: Entry) -> list[str]:
    """Return the distinct pane names of every occurrence of the entry, newest first."""
    names = [pane.name for occurrence in entry.occurrences for pane in occurrence.tab.panes]
    return list(dict.fromkeys(names))


def _shell_line(entry: Entry, query: str, colors: Palette) -> str:
    """Return the shell entry's second line: the folder, then the distinct pane names."""
    folder = highlight(short_path(entry.newest.tab.panes[0].path), query, colors.gold)
    names = ", ".join(highlight(name, query, colors.gold) for name in _shell_names(entry))
    return f"    {folder} · names: {names}"


def _agent_session_line(entry: Entry, query: str, colors: Palette) -> str:
    """Return the agent entry's third line: the agent folder and the start of its session ID."""
    agent = _first_agent(entry.newest.tab)
    folder = highlight(short_path(agent.cwd), query, colors.gold)
    return f"    {folder} · session {agent.session_id[:8]}"


def _period_line(entry: Entry, colors: Palette) -> str:
    """Return the entry's last line: its period, snapshot count, and pin when the newest one is pinned."""
    summaries = entry.summaries
    newest_summary, oldest_summary = summaries[0], summaries[-1]
    period_text = period(oldest_summary.created_at, newest_summary.created_at)
    line = f"    [{colors.cyan}]{period_text}[/][dim] · {counted_snapshots(len(summaries))}[/dim]"
    if newest_summary.pinned:
        line += f"[dim] · last 📌 {PIN_LABELS[newest_summary.pinned]}[/dim]"
    return line


def entry_markup(entry: Entry, query: str, colors: Palette) -> str:
    """Return the collapsed view of a history entry, as Rich markup: heading, titles, period."""
    lines = [_entry_heading_line(entry, query, colors)]
    if entry.has_agent:
        lines.append(_agent_titles_line(entry, query, colors))
        lines.append(_agent_session_line(entry, query, colors))
    else:
        lines.append(_shell_line(entry, query, colors))
    lines.append(_period_line(entry, colors))
    return "\n".join(lines)


def variant_markup(variant: Variant, last: bool, query: str, colors: Palette) -> str:
    """Return one line of an expanded entry: the variant text, its period, and its snapshot count."""
    marker = "└" if last else "├"
    parts = dict.fromkeys(part for part in variant.text if part)
    text = " · ".join(parts).ljust(24)
    summaries = variant.summaries
    period_text = period(summaries[-1].created_at, summaries[0].created_at)
    line = f"[{colors.cyan}]{period_text}[/][dim] · {counted_snapshots(len(summaries))}[/dim]"
    return f"      {marker} {highlight(text, query, colors.gold)}{line}"


def print_sessions(snapshot: Snapshot, colors: Palette) -> None:
    """Print every tab of a snapshot as a short list: the tab heading, then the session of each pane."""
    summary = snapshot.summary
    pin = f" · 📌 {PIN_LABELS.get(summary.pinned, summary.pinned)}" if summary.pinned else ""
    console.print(f"[bold]Snapshot {summary.id}[/bold] · {summary.tabs} tabs · {summary.agents} agents{pin}"
                  f"   [{colors.green}]●[/] still runs\n")
    for position, tab in positioned_tabs(snapshot.windows):
        console.print(tab_markup(position, tab, colors) + "\n", highlight=False)

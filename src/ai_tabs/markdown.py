"""The optional Markdown views, to read in Obsidian or any Markdown viewer.

When `markdown_dir` is set, every new snapshot writes:

* `ai-tabs.md`: the latest snapshot, with a table of the panes and the resume commands;
* `history/YYYY-MM-DD.md`: one file per day, with one section for each snapshot of the day
  and the changes it records.

The database stays the only source of the data: nothing reads these files back.
"""

import shlex
from datetime import date, timedelta
from pathlib import Path

from .config import HISTORY_DAYS
from .diff import render_changes
from .models import Pane, Tab, Window, positioned_tabs
from .store import Snapshot


def tab_label(position: str, tab: Tab) -> str:
    """Return the label of a tab: its title, or the name of its first pane."""
    return f"{position} {tab.title or tab.panes[0].name}"


def color_text(color: list[int] | None) -> str:
    """Return an RGB color as hex text, or an empty string."""
    return "#{:02x}{:02x}{:02x}".format(*color) if color else ""


def summary_row(position: str, tab: Tab, pane: Pane) -> str:
    """Return the summary table row of one pane."""
    agent = pane.agent
    cells = [position, tab.title or pane.name, color_text(tab.color),
             agent.kind if agent else "shell", agent.title if agent else "",
             f"`{agent.session_id}`" if agent else "", f"`{agent.cwd if agent else pane.path}`"]
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def pane_details(pane: Pane) -> list[str]:
    """Return the detail lines and the resume command of one pane."""
    agent = pane.agent
    lines = [f"- iTerm session name: {pane.name}", f"- Shell folder: `{pane.path}`"]
    if agent:
        lines.append(f"- Agent: {agent.kind}, session `{agent.session_id}`, folder `{agent.cwd}`")
    command = agent.resume if agent else f"cd {shlex.quote(pane.path)}"
    return lines + ["", "```sh", command, "```", ""]


def render_sessions(windows: list[Window]) -> list[str]:
    """Return the summary table and the resume commands of all panes."""
    tabs = positioned_tabs(windows)
    lines = ["| Tab | Title | Color | Agent | Session title | Session ID | Folder |",
             "|---|---|---|---|---|---|---|"]
    lines += [summary_row(position, tab, pane) for position, tab in tabs for pane in tab.panes]
    lines += ["", "## Resume commands", ""]
    for position, tab in tabs:
        lines += [f"### {tab_label(position, tab)}", ""]
        for pane in tab.panes:
            lines += pane_details(pane)
    return lines


def render_latest(snapshot: Snapshot) -> str:
    """Return the Markdown view of the latest snapshot."""
    summary = snapshot.summary
    header = ["# iTerm2 sessions", "", f"Updated: {summary.created_at:%Y-%m-%d %H:%M:%S} (`{summary.id}`)", "",
              "To pick the tabs to open again, run `ai-tabs`.", ""]
    return "\n".join(header + render_sessions(snapshot.windows))


def render_day_entry(snapshot: Snapshot, pin_note: str | None) -> str:
    """Return the section of one snapshot in the file of its day."""
    summary = snapshot.summary
    lines = [f"## {summary.created_at:%H:%M:%S}", "",
             f"`{summary.id}` · {summary.tabs} tabs · {summary.agents} agents", "", *render_changes(snapshot.changes)]
    if pin_note:
        lines.append(f"- {pin_note}")
    return "\n".join(lines) + "\n\n"


def day_file(markdown_dir: Path, day: date) -> Path:
    """Return the Markdown file of a day."""
    return markdown_dir / "history" / f"{day:%Y-%m-%d}.md"


def day_header(day: date) -> str:
    """Return the first lines of a new day file."""
    return (f"# iTerm2 sessions — {day:%Y-%m-%d}\n\n"
            "To see a snapshot, run `ai-tabs show ID`. To open it again, run `ai-tabs restore --from ID`.\n\n")


def write_atomically(path: Path, content: str) -> None:
    """Replace the file in one step, so that a crash never leaves half a file."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def write_views(markdown_dir: Path, snapshot: Snapshot, pin_note: str | None) -> None:
    """Write the latest snapshot and add the snapshot to the file of its day."""
    day = snapshot.summary.created_at.date()
    target = day_file(markdown_dir, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(markdown_dir / "ai-tabs.md", render_latest(snapshot))
    previous = target.read_text() if target.exists() else day_header(day)
    write_atomically(target, previous + render_day_entry(snapshot, pin_note))


def prune_days(markdown_dir: Path, today: date) -> None:
    """Delete the day files older than HISTORY_DAYS, like the snapshots in the database."""
    oldest = f"{today - timedelta(days=HISTORY_DAYS):%Y-%m-%d}"
    for old in (markdown_dir / "history").glob("????-??-??.md"):
        if old.stem < oldest:
            old.unlink()

"""The Markdown export of snapshots, to read in Obsidian or any Markdown viewer.

`ai-tabs export` writes one file per snapshot: `export_dir/YYYY-MM-DD/HH-MM-SS.md`. With
`export_latest = true`, every new snapshot also rewrites `export_dir/latest.md`. The database
stays the only source of the data: nothing reads these files back.
"""

import shlex
from pathlib import Path

from .diff import render_changes
from .models import Pane, Tab, Window, positioned_tabs
from .store import PIN_LABELS, Snapshot


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
    if pane.profile:
        lines.append(f"- iTerm2 profile: {pane.profile}")
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


def front_matter(snapshot: Snapshot) -> list[str]:
    """Return the YAML front matter of an export, for Obsidian properties and Dataview."""
    summary = snapshot.summary
    pin = PIN_LABELS.get(summary.pinned, summary.pinned) if summary.pinned else "no"
    return ["---", f"id: {summary.id}", f"created: {summary.created_at:%Y-%m-%d %H:%M:%S}",
            f"tabs: {summary.tabs}", f"agents: {summary.agents}", f"opened: {summary.opened}",
            f"closed: {summary.closed}", f"changed: {summary.changed}", f"pinned: {pin}", "---", ""]


def render_snapshot(snapshot: Snapshot) -> str:
    """Return the Markdown export of one snapshot: front matter, changes, panes and commands."""
    summary = snapshot.summary
    body = [f"# iTerm2 tabs — {summary.created_at:%Y-%m-%d %H:%M:%S}", "",
            f"To pick these tabs again, run `ai-tabs restore --from {summary.id}`.", "",
            "## Changes", "", *render_changes(snapshot.changes), "", "## Sessions", "",
            *render_sessions(snapshot.windows)]
    return "\n".join(front_matter(snapshot) + body)


def write_atomically(path: Path, content: str) -> None:
    """Replace the file in one step, so that a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def export_snapshot(snapshot: Snapshot, export_dir: Path) -> Path:
    """Write the export of a snapshot to `export_dir/YYYY-MM-DD/HH-MM-SS.md` and return the file."""
    target = export_dir / f"{snapshot.summary.id}.md"
    write_atomically(target, render_snapshot(snapshot))
    return target


def write_latest(snapshot: Snapshot, export_dir: Path) -> Path:
    """Write the export of a snapshot to `export_dir/latest.md` and return the file."""
    target = export_dir / "latest.md"
    write_atomically(target, render_snapshot(snapshot))
    return target

"""The changes between two snapshots: the panes that opened, closed or changed."""

from .models import Pane, Tab, Window, positioned_tabs


def pane_key(pane: Pane) -> str:
    """Return a key that follows a pane from one snapshot to the next."""
    return f"{pane.agent.kind} {pane.agent.session_id}" if pane.agent else f"shell {pane.tty}"


def pane_text(tab: Tab, pane: Pane) -> str:
    """Return a one-line description of a pane for the change list, as Markdown."""
    agent = pane.agent
    what = f"{agent.kind} “{agent.title}” in `{agent.cwd}`" if agent else f"shell in `{pane.path}`"
    return f"**{tab.title or pane.name}**: {what}"


def pane_index(windows: list[Window]) -> dict[str, str]:
    """Map the key of every pane to its description."""
    return {pane_key(pane): pane_text(tab, pane) for _, tab in positioned_tabs(windows) for pane in tab.panes}


def changes(previous: list[Window], current: list[Window]) -> dict[str, list[str]]:
    """Return the panes that opened, closed or changed between two snapshots, sorted."""
    before, after = pane_index(previous), pane_index(current)
    return {
        "opened": sorted(after[key] for key in after.keys() - before.keys()),
        "closed": sorted(before[key] for key in before.keys() - after.keys()),
        "changed": sorted(f"{before[key]} → {after[key]}" for key in before.keys() & after.keys()
                          if before[key] != after[key]),
    }


def render_changes(diff: dict[str, list[str]]) -> list[str]:
    """Return the change list as Markdown lines, or a note when only details changed."""
    lines = [f"- {kind.capitalize()}: {text}" for kind, texts in diff.items() for text in texts]
    return lines or ["- Only details changed (PID, TTY, window frame or order)."]

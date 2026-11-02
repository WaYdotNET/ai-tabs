"""Take a snapshot: read iTerm2, store it when it changed, pin, export, prune and back up."""

import sys
from datetime import datetime

import iterm2

from . import markdown, store
from .config import settings
from .diff import changes
from .iterm import read_windows
from .models import Window, tab_count
from .system import boot_time


def auto_pin_reason(previous: store.Summary, windows: list[Window], boot: datetime | None) -> str | None:
    """Return why the previous snapshot needs a pin, or None.

    * `before-boot`: it is the last snapshot from before the current boot of the Mac.
    * `before-drop`: the new snapshot holds less than half of its tabs, as after a crash of iTerm2.
    """
    if boot is not None and previous.created_at < boot:
        return "before-boot"
    before, after = previous.tabs, tab_count(windows)
    return "before-drop" if before >= 2 and after * 2 < before else None


def pin_previous(previous: store.Snapshot | None, windows: list[Window]) -> str | None:
    """Pin the previous snapshot when it is the state from before a boot or a crash.

    A snapshot that already has a pin keeps it. Return a note for the Markdown views, or None.
    """
    if previous is None or previous.summary.pinned:
        return None
    reason = auto_pin_reason(previous.summary, windows, boot_time())
    if reason is None:
        return None
    store.set_pin(previous.summary.id, reason)
    return f"Pinned `{previous.summary.id}`: {store.PIN_LABELS[reason]}"


def export_markdown(snapshot_id: str, pin_note: str | None) -> None:
    """Write the Markdown views of a new snapshot, when `markdown_dir` is set."""
    markdown_dir = settings().markdown_dir
    snapshot = store.snapshot_by_id(snapshot_id)
    if markdown_dir is None or snapshot is None:
        return
    markdown.write_views(markdown_dir, snapshot, pin_note)
    markdown.prune_days(markdown_dir, snapshot.summary.created_at.date())


def record_snapshot(windows: list[Window], moment: datetime) -> str | None:
    """Store the windows as a new snapshot if they changed. Return the new ID, or None."""
    previous = store.latest_snapshot()
    if previous is not None and previous.windows == windows:
        return None
    diff = changes(previous.windows if previous else [], windows)
    new_id = store.insert_snapshot(windows, diff, moment)
    export_markdown(new_id, pin_previous(previous, windows))
    store.prune(moment.date())
    store.backup_if_due(moment.date())
    return new_id


async def take_snapshot(connection: iterm2.Connection) -> None:
    """Take the snapshot. Keep the previous snapshot when iTerm2 has no windows."""
    windows = await read_windows(connection)
    if not windows:
        print("No iTerm2 windows: the previous snapshot stays.", file=sys.stderr)
        return
    new_id = record_snapshot(windows, datetime.now())
    panes = sum(len(tab.panes) for window in windows for tab in window.tabs)
    status = f"Wrote snapshot {new_id}" if new_id else "No change"
    print(f"{datetime.now():%H:%M:%S} {status} ({panes} panes)")

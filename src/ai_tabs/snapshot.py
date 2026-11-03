"""Take a snapshot: read iTerm2, store it when it changed, pin, export, prune and back up."""

import fcntl
import sys
from collections.abc import Iterator
from contextlib import contextmanager
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
    * `before-drop`: the new snapshot holds less than half of its tabs, as after a crash of iTerm2
      or when many tabs close at once.
    """
    if boot is not None and previous.created_at < boot:
        return "before-boot"
    before, after = previous.tabs, tab_count(windows)
    return "before-drop" if before >= 2 and after * 2 < before else None


def pin_previous(previous: store.Snapshot | None, windows: list[Window]) -> None:
    """Pin the previous snapshot when it is the state from before a boot or a crash.

    A snapshot that already has a pin keeps it.
    """
    if previous is None or previous.summary.pinned:
        return
    reason = auto_pin_reason(previous.summary, windows, boot_time())
    if reason is not None:
        store.set_pin(previous.summary.id, reason)


def export_latest(snapshot_id: str) -> None:
    """Rewrite `export_dir/latest.md` with a new snapshot, when `export_latest` is on."""
    snapshot = store.snapshot_by_id(snapshot_id)
    if settings().export_latest and snapshot is not None:
        markdown.write_latest(snapshot, settings().export_dir)


@contextmanager
def snapshot_lock() -> Iterator[None]:
    """Hold the lock file of the snapshots until the block ends. Wait while another process holds it."""
    path = settings().data_dir / "snapshot.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Two processes write snapshots at the same time: the watcher and the launchd interval agent.
    with path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def record_snapshot(windows: list[Window], moment: datetime) -> str | None:
    """Store the windows as a new snapshot if they changed, under the snapshot lock. Return the new ID, or None."""
    with snapshot_lock():
        return store_if_changed(windows, moment)


def store_if_changed(windows: list[Window], moment: datetime) -> str | None:
    """Store the windows as a new snapshot if they changed, then pin, export, prune and back up."""
    previous = store.latest_snapshot()
    if previous is not None and previous.windows == windows:
        return None
    diff = changes(previous.windows if previous else [], windows)
    new_id = store.insert_snapshot(windows, diff, moment)
    pin_previous(previous, windows)
    export_latest(new_id)
    store.prune(moment.date())
    store.backup_if_due(moment.date())
    return new_id


async def take_snapshot(connection: iterm2.Connection, prefix: str = "") -> None:
    """Take the snapshot and log it. Keep the previous snapshot when iTerm2 has no windows.

    `prefix` starts each log line, so that the log shows which process took the snapshot.
    """
    windows = await read_windows(connection)
    if not windows:
        print(f"{prefix}No iTerm2 windows: the previous snapshot stays.", file=sys.stderr)
        return
    new_id = record_snapshot(windows, datetime.now())
    panes = sum(len(tab.panes) for window in windows for tab in window.tabs)
    status = f"Wrote snapshot {new_id}" if new_id else "No change"
    print(f"{prefix}{datetime.now():%H:%M:%S} {status} ({panes} panes)")

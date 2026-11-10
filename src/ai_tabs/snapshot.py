"""Take a snapshot: read iTerm2, store it when it changed, pin, export, prune and back up."""

import fcntl
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import iterm2

from . import markdown, store
from .config import settings
from .diff import changes
from .iterm import read_windows
from .models import Window, differ_only_in_sizes, tab_count
from .system import boot_time


class Outcome(Enum):
    """What a record of the windows did to the history."""

    WROTE = "Wrote snapshot {id}"
    UPDATED = "Updated snapshot {id} (sizes only)"
    UNCHANGED = "No change"


@dataclass(frozen=True)
class Recorded:
    """The outcome of a record, and the ID of the snapshot that it wrote or updated."""

    outcome: Outcome
    snapshot_id: str | None = None

    def status(self) -> str:
        """Return the log text of the outcome."""
        return self.outcome.value.format(id=self.snapshot_id)


UNCHANGED = Recorded(Outcome.UNCHANGED)


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


def record_snapshot(windows: list[Window], moment: datetime) -> Recorded:
    """Store the windows if they changed, under the snapshot lock, and return what the record did."""
    with snapshot_lock():
        return store_if_changed(windows, moment)


def store_if_changed(windows: list[Window], moment: datetime) -> Recorded:
    """Store the windows if they changed, and return what the record did.

    A change of window frames or pane sizes only updates the latest snapshot. Other changes add a new snapshot.
    """
    previous = store.latest_snapshot()
    if previous is not None and previous.windows == windows:
        return UNCHANGED
    if previous is not None and can_update_in_place(previous, windows):
        return update_in_place(previous, windows, moment)
    return insert_new(previous, windows, moment)


def can_update_in_place(previous: store.Snapshot, windows: list[Window]) -> bool:
    """Return True when the windows can replace those of the previous snapshot.

    The windows must differ only in frames and pane sizes. A snapshot with a pin, or one that gets an
    automatic pin now, keeps its windows: it is the state that a pin protects.
    """
    gets_no_pin = auto_pin_reason(previous.summary, windows, boot_time()) is None
    keeps_no_pin = previous.summary.pinned is None and gets_no_pin
    return keeps_no_pin and differ_only_in_sizes(previous.windows, windows)


def update_in_place(previous: store.Snapshot, windows: list[Window], moment: datetime) -> Recorded:
    """Replace the windows of the previous snapshot and export it.

    When a pin came after the read of the previous snapshot, insert a new snapshot.
    """
    if not store.update_windows(previous.summary.id, windows):
        return insert_new(previous, windows, moment)
    export_latest(previous.summary.id)
    return Recorded(Outcome.UPDATED, previous.summary.id)


def insert_new(previous: store.Snapshot | None, windows: list[Window], moment: datetime) -> Recorded:
    """Store the windows as a new snapshot, then pin the previous snapshot when needed and export."""
    diff = changes(previous.windows if previous else [], windows)
    new_id = store.insert_snapshot(windows, diff, moment)
    pin_previous(previous, windows)
    export_latest(new_id)
    return Recorded(Outcome.WROTE, new_id)


def maintain(moment: datetime) -> None:
    """Run the daily maintenance when it is due, under the snapshot lock.

    The prune comes before the backup, so that the backup holds the pruned database.
    """
    with snapshot_lock():
        if not store.maintenance_due(moment):
            return
        store.prune(moment.date())
        store.daily_backup(moment)


def log_snapshot(windows: list[Window], moment: datetime, prefix: str) -> None:
    """Record the windows and log the result."""
    recorded = record_snapshot(windows, moment)
    panes = sum(len(tab.panes) for window in windows for tab in window.tabs)
    print(f"{prefix}{moment:%H:%M:%S} {recorded.status()} ({panes} panes)")


async def take_snapshot(connection: iterm2.Connection, prefix: str = "") -> None:
    """Take the snapshot and log it, then run the daily maintenance, also when nothing changed.

    The previous snapshot stays when iTerm2 has no windows. `prefix` starts each log line, so that
    the log shows which process took the snapshot.
    """
    windows = await read_windows(connection)
    moment = datetime.now()
    if windows:
        log_snapshot(windows, moment, prefix)
    else:
        print(f"{prefix}No iTerm2 windows: the previous snapshot stays.", file=sys.stderr)
    maintain(moment)

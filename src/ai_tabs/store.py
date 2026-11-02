"""The snapshot database: one SQLite file with every snapshot.

A snapshot ID is `YYYY-MM-DD/HH-MM-SS`, the local time when the snapshot was taken, so the IDs
sort in time order. `latest` is an alias of the newest snapshot.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import HISTORY_DAYS, settings
from .models import Window, agent_count, tab_count, windows_from_json, windows_to_json

LATEST = "latest"
PIN_LABELS = {"manual": "pinned", "before-boot": "before boot", "before-drop": "before crash"}
AUTO_PINS = ("before-boot", "before-drop")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    windows TEXT NOT NULL,
    tabs INTEGER NOT NULL,
    agents INTEGER NOT NULL,
    changes TEXT NOT NULL,
    pinned TEXT
);
"""
SUMMARY_COLUMNS = """id, created_at, tabs, agents, pinned,
    json_array_length(changes, '$.opened') AS opened,
    json_array_length(changes, '$.closed') AS closed,
    json_array_length(changes, '$.changed') AS changed"""
SELECT_SNAPSHOT = f"SELECT {SUMMARY_COLUMNS}, windows, changes FROM snapshots"


@dataclass(frozen=True)
class Summary:
    """What a snapshot holds, without its windows: enough for the lists."""

    id: str
    created_at: datetime
    tabs: int
    agents: int
    opened: int
    closed: int
    changed: int
    pinned: str | None


@dataclass(frozen=True)
class Snapshot:
    """A snapshot with its windows and the changes since the snapshot before it."""

    summary: Summary
    windows: list[Window]
    changes: dict[str, list[str]]


def snapshot_id(moment: datetime) -> str:
    """Return the ID of a snapshot taken at a moment."""
    return f"{moment:%Y-%m-%d/%H-%M-%S}"


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    """Open the database in a transaction, create the table when needed, and close it after."""
    path = settings().database
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        yield connection


def summary_from_row(row: sqlite3.Row) -> Summary:
    """Build a Summary from a database row."""
    return Summary(row["id"], datetime.fromisoformat(row["created_at"]), row["tabs"], row["agents"],
                   row["opened"], row["closed"], row["changed"], row["pinned"])


def snapshot_from_row(row: sqlite3.Row) -> Snapshot:
    """Build a Snapshot from a database row."""
    return Snapshot(summary_from_row(row), windows_from_json(row["windows"]), json.loads(row["changes"]))


def insert_snapshot(windows: list[Window], changes: dict[str, list[str]], moment: datetime) -> str:
    """Store a new snapshot and return its ID. A second snapshot in the same second replaces the first."""
    new_id = snapshot_id(moment)
    values = (new_id, f"{moment:%Y-%m-%d %H:%M:%S}", windows_to_json(windows), tab_count(windows),
              agent_count(windows), json.dumps(changes, ensure_ascii=False))
    with database() as db:
        db.execute("INSERT OR REPLACE INTO snapshots (id, created_at, windows, tabs, agents, changes, pinned) "
                   "VALUES (?, ?, ?, ?, ?, ?, NULL)", values)
    return new_id


def latest_snapshot() -> Snapshot | None:
    """Return the newest snapshot, or None when the database is empty."""
    with database() as db:
        row = db.execute(f"{SELECT_SNAPSHOT} ORDER BY id DESC LIMIT 1").fetchone()
    return snapshot_from_row(row) if row else None


def snapshot_by_id(wanted: str) -> Snapshot | None:
    """Return the snapshot with an ID, or None when there is none."""
    with database() as db:
        row = db.execute(f"{SELECT_SNAPSHOT} WHERE id = ?", (wanted,)).fetchone()
    return snapshot_from_row(row) if row else None


def find_snapshot(reference: str) -> Snapshot | None:
    """Return the snapshot of a reference: `latest` or a snapshot ID."""
    return latest_snapshot() if reference == LATEST else snapshot_by_id(reference)


def summaries(limit: int | None = None) -> list[Summary]:
    """Return the summaries of the snapshots, newest first. Without a limit, return all of them."""
    with database() as db:
        rows = db.execute(f"SELECT {SUMMARY_COLUMNS} FROM snapshots ORDER BY id DESC LIMIT ?", (limit or -1,))
        return [summary_from_row(row) for row in rows]


def set_pin(wanted: str, reason: str | None) -> bool:
    """Pin a snapshot with a reason, or unpin it with None. Return False when the ID is unknown."""
    with database() as db:
        return db.execute("UPDATE snapshots SET pinned = ? WHERE id = ?", (reason, wanted)).rowcount == 1


def prune(today: date) -> int:
    """Delete the snapshots older than HISTORY_DAYS. Return how many went.

    Pinned snapshots stay, and so does the newest snapshot, however old it is.
    """
    oldest = f"{today - timedelta(days=HISTORY_DAYS):%Y-%m-%d}"
    with database() as db:
        return db.execute("DELETE FROM snapshots WHERE pinned IS NULL AND created_at < ? "
                          "AND id < (SELECT MAX(id) FROM snapshots)", (oldest,)).rowcount


def recommended_id() -> str | None:
    """Return the snapshot that the restore screen starts on, or None when there is none.

    It is the newest automatic pin when every newer snapshot holds fewer tabs: the state from
    before a reboot or a crash, when nobody restored it yet. Otherwise it is the newest snapshot.
    """
    with database() as db:
        newest = db.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        pin = db.execute("SELECT id, tabs FROM snapshots WHERE pinned IN (?, ?) ORDER BY id DESC LIMIT 1",
                         AUTO_PINS).fetchone()
        if pin is None:
            return newest["id"] if newest else None
        bigger = db.execute("SELECT COUNT(*) FROM snapshots WHERE id > ? AND tabs >= ?",
                            (pin["id"], pin["tabs"])).fetchone()[0]
    return newest["id"] if bigger else pin["id"]


def backup_path(day: date) -> Path:
    """Return the backup file of a day."""
    return settings().backup_dir / f"ai-tabs-{day:%Y-%m-%d}.sqlite"


def write_backup(day: date) -> Path:
    """Write a consistent copy of the database for a day, keep the newest backups, return the copy."""
    target = backup_path(day)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with database():
        pass
    # VACUUM INTO cannot run inside a transaction, so it gets its own connection.
    with closing(sqlite3.connect(settings().database)) as connection:
        connection.execute("VACUUM INTO ?", (str(target),))
    prune_backups()
    return target


def backup_if_due(day: date) -> Path | None:
    """Write the backup of the day when it does not exist yet. Return it, or None."""
    return None if backup_path(day).exists() else write_backup(day)


def prune_backups() -> None:
    """Delete the oldest backups, so that only the newest `backup_keep` stay."""
    backups = sorted(settings().backup_dir.glob("ai-tabs-????-??-??.sqlite"), reverse=True)
    for old in backups[settings().backup_keep:]:
        old.unlink()

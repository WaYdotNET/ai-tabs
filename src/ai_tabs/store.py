"""The snapshot database: one SQLite file with every snapshot.

A snapshot ID is `YYYY-MM-DD/HH-MM-SS`, the local time when the snapshot was taken, so the IDs
sort in time order. `latest` is an alias of the newest snapshot.
"""

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import settings
from .models import Window, agent_count, tab_count, windows_from_json, windows_to_json

LATEST = "latest"
PIN_LABELS = {"manual": "pinned", "before-boot": "before boot", "before-drop": "before tabs closed"}
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


def all_snapshots() -> list[Snapshot]:
    """Return every snapshot with its windows and changes, newest first."""
    with database() as db:
        rows = db.execute(f"{SELECT_SNAPSHOT} ORDER BY id DESC")
        return [snapshot_from_row(row) for row in rows]


def set_pin(wanted: str, reason: str | None) -> bool:
    """Pin a snapshot with a reason, or unpin it with None. Return False when the ID is unknown."""
    with database() as db:
        return db.execute("UPDATE snapshots SET pinned = ? WHERE id = ?", (reason, wanted)).rowcount == 1


def update_windows(wanted: str, windows: list[Window]) -> bool:
    """Replace the windows of an unpinned snapshot. Return False when the ID is unknown or the snapshot has a pin.

    The ID, the time, the counts and the changes stay. Use this function only for windows with the same tabs.
    """
    with database() as db:
        query = "UPDATE snapshots SET windows = ? WHERE id = ? AND pinned IS NULL"
        return db.execute(query, (windows_to_json(windows), wanted)).rowcount == 1


def prune(today: date) -> int:
    """Delete the snapshots older than `history_days`. Return how many went.

    Pinned snapshots stay, and so does the newest snapshot, however old it is.
    """
    oldest = f"{today - timedelta(days=settings().history_days):%Y-%m-%d}"
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


def backup_slot(moment: datetime) -> datetime | None:
    """Return the latest time of `backup_times` on the day of the moment that is not after it, or None."""
    started = [clock for clock in settings().backup_times if time.fromisoformat(clock) <= moment.time()]
    if not started:
        return None
    return datetime.combine(moment.date(), time.fromisoformat(started[-1]))


def maintenance_due(moment: datetime) -> bool:
    """Tell if the maintenance is due: a time of `backup_times` started, and the day backup is older or missing."""
    slot = backup_slot(moment)
    if slot is None:
        return False
    target = backup_path(moment.date())
    return not target.exists() or target.stat().st_mtime < slot.timestamp()


def daily_backup(moment: datetime) -> Path:
    """Write the backup of the day, or reuse the newest backup when it holds the same data. Return it.

    The backup gets the moment as its modification time, also after a rename. A rename keeps the
    old time, and without the new time `maintenance_due` finds the slot due again at each run.
    """
    target = backup_path(moment.date())
    unchanged = unchanged_backup()
    if unchanged is None:
        write_backup(moment.date())
    else:
        unchanged.replace(target)
    stamp = moment.timestamp()
    os.utime(target, (stamp, stamp))
    return target


def unchanged_backup() -> Path | None:
    """Return the newest backup when it holds the same data as the live database, else None."""
    files = backup_files()
    if files and backup_fingerprint(files[0]) == live_fingerprint():
        return files[0]
    return None


def fingerprint(connection: sqlite3.Connection) -> str:
    """Return a sha256 digest of the rows of every table, so that two databases with the same data match."""
    digest = hashlib.sha256()
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    for (table,) in tables:
        digest.update(table.encode())
        # The first column is the primary key of each table, so the order does not depend on the file.
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY 1'):
            digest.update(repr(tuple(row)).encode())
    return digest.hexdigest()


def live_fingerprint() -> str:
    """Return the fingerprint of the live database."""
    with database() as connection:
        return fingerprint(connection)


def backup_fingerprint(path: Path) -> str | None:
    """Return the fingerprint of a backup opened read only, or None when it cannot be read."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            return fingerprint(connection)
    except sqlite3.DatabaseError:
        return None


def backup_files() -> list[Path]:
    """Return the daily backups, newest first."""
    return sorted(settings().backup_dir.glob("ai-tabs-????-??-??.sqlite"), reverse=True)


def prune_backups() -> None:
    """Delete the oldest backups, so that only the newest `backup_keep` stay."""
    for old in backup_files()[settings().backup_keep:]:
        old.unlink()

"""List the daily backups and restore one of them into the live database."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import store
from .config import settings

LATEST = "latest"
BACKUP_GLOB = "ai-tabs-????-??-??.sqlite"


class BackupError(Exception):
    """A backup does not exist or is not a valid snapshot database."""


@dataclass(frozen=True)
class BackupInfo:
    day: date
    path: Path
    size: int
    snapshots: int | None


@dataclass(frozen=True)
class RestoreResult:
    safety_copy: Path
    snapshots: int


def read_only(path: Path) -> sqlite3.Connection:
    """Open a database file read only, so that a read never changes the file."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def backup_day(path: Path) -> date:
    """Return the day in the name of a backup file."""
    return date.fromisoformat(path.stem.removeprefix("ai-tabs-"))


def snapshot_count(path: Path) -> int:
    """Return the number of snapshots in a database file."""
    with closing(read_only(path)) as connection:
        return connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def count_or_none(path: Path) -> int | None:
    """Return the number of snapshots in a backup, or None when the backup cannot be read."""
    try:
        return snapshot_count(path)
    except sqlite3.DatabaseError:
        return None


def backup_files() -> list[Path]:
    """Return the backup files, newest first."""
    return sorted(settings().backup_dir.glob(BACKUP_GLOB), reverse=True)


def list_backups() -> list[BackupInfo]:
    """Return the date, the size and the snapshot count of each backup, newest first."""
    return [BackupInfo(backup_day(path), path, path.stat().st_size, count_or_none(path)) for path in backup_files()]


def find_backup(reference: str) -> Path:
    """Return the backup of a `YYYY-MM-DD` date or of `latest`. Raise BackupError when it does not exist."""
    files = backup_files()
    wanted = files[:1] if reference == LATEST else [path for path in files if path.stem == f"ai-tabs-{reference}"]
    if wanted:
        return wanted[0]
    days = ", ".join(f"{backup_day(path)}" for path in files) or "none"
    raise BackupError(f"No backup for {reference}. Backups that exist: {days}.")


def integrity(path: Path) -> str:
    """Return the result of `PRAGMA integrity_check` and fail when there is no snapshots table."""
    with closing(read_only(path)) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        connection.execute("SELECT 1 FROM snapshots LIMIT 1")
    return result


def check_backup(path: Path) -> None:
    """Raise BackupError when a backup is damaged or does not hold a snapshots table."""
    try:
        result = integrity(path)
    except sqlite3.DatabaseError as error:
        raise BackupError(f"{path} is not a valid snapshot database: {error}") from error
    if result != "ok":
        raise BackupError(f"{path} fails the integrity check: {result}")


def current_count() -> int:
    """Return the number of snapshots in the live database."""
    with store.database() as connection:
        return connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def safety_copy_path(moment: datetime) -> Path:
    """Return the path of the copy of the live database made before a restore."""
    return settings().backup_dir / f"ai-tabs-before-restore-{moment:%Y-%m-%d-%H%M%S}.sqlite"


def write_safety_copy(moment: datetime) -> Path:
    """Write a consistent copy of the live database before a restore and return it."""
    target = safety_copy_path(moment)
    target.parent.mkdir(parents=True, exist_ok=True)
    with store.database():
        pass
    # VACUUM INTO cannot run inside a transaction, so it gets its own connection.
    with closing(sqlite3.connect(settings().database)) as connection:
        connection.execute("VACUUM INTO ?", (str(target),))
    return target


def copy_into_live(path: Path) -> None:
    """Copy a backup into the live database with the SQLite online backup API.

    The launchd agent can write to the database at the same moment. The backup API copies under a lock,
    and a file copy does not.
    """
    with closing(read_only(path)) as source, closing(sqlite3.connect(settings().database)) as target:
        source.backup(target)


def restore_backup(path: Path, moment: datetime) -> RestoreResult:
    """Check a backup, save the live database, then replace the live database with the backup."""
    check_backup(path)
    safety = write_safety_copy(moment)
    copy_into_live(path)
    return RestoreResult(safety, current_count())

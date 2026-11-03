"""Listing the daily backups and restoring one into the live database."""

import sqlite3
from contextlib import closing
from datetime import date, datetime

import pytest
from factories import windows_with_tabs
from typer.testing import CliRunner

from ai_tabs import backups, store
from ai_tabs.cli import app
from ai_tabs.config import settings

NO_CHANGES = {"opened": [], "closed": [], "changed": []}
RESTORE_MOMENT = datetime(2026, 11, 3, 9, 30, 15)
runner = CliRunner()


def insert(moment: datetime) -> str:
    """Store a snapshot with one shell tab at a moment and return its ID."""
    return store.insert_snapshot(windows_with_tabs(1), NO_CHANGES, moment)


def snapshot_ids(path) -> list[str]:
    """Return the snapshot IDs in a database file, oldest first."""
    with closing(backups.read_only(path)) as connection:
        return [row[0] for row in connection.execute("SELECT id FROM snapshots ORDER BY id")]


def two_backups() -> None:
    """Write a backup with one snapshot on 1 November and one with two snapshots on 2 November."""
    insert(datetime(2026, 11, 1, 10, 0, 0))
    store.write_backup(date(2026, 11, 1))
    insert(datetime(2026, 11, 2, 10, 0, 0))
    store.write_backup(date(2026, 11, 2))


def test_list_shows_the_newest_backup_first_with_its_snapshot_count():
    two_backups()

    listed = backups.list_backups()

    assert [(info.day, info.snapshots) for info in listed] == [(date(2026, 11, 2), 2), (date(2026, 11, 1), 1)]


def test_restore_replaces_the_snapshots_with_the_ones_of_the_backup():
    two_backups()
    insert(datetime(2026, 11, 3, 8, 0, 0))

    result = backups.restore_backup(backups.find_backup("2026-11-01"), RESTORE_MOMENT)

    assert result.snapshots == 1
    assert snapshot_ids(settings().database) == ["2026-11-01/10-00-00"]


def test_safety_copy_keeps_the_rows_of_the_old_database():
    two_backups()
    insert(datetime(2026, 11, 3, 8, 0, 0))

    result = backups.restore_backup(backups.find_backup("2026-11-01"), RESTORE_MOMENT)

    assert result.safety_copy.name == "ai-tabs-before-restore-2026-11-03-093015.sqlite"
    assert snapshot_ids(result.safety_copy) == ["2026-11-01/10-00-00", "2026-11-02/10-00-00", "2026-11-03/08-00-00"]


def test_daily_prune_glob_does_not_match_the_safety_copy():
    two_backups()

    safety = backups.write_safety_copy(RESTORE_MOMENT)

    assert safety.match("ai-tabs-????-??-??.sqlite") is False


def test_corrupt_backup_is_refused_and_the_live_database_does_not_change():
    two_backups()
    corrupt = settings().backup_dir / "ai-tabs-2026-11-03.sqlite"
    corrupt.write_bytes(b"this is not a database" * 100)

    result = runner.invoke(app, ["backup", "--restore", "2026-11-03", "--yes"])

    assert result.exit_code == 1
    assert snapshot_ids(settings().database) == ["2026-11-01/10-00-00", "2026-11-02/10-00-00"]


def test_backup_without_snapshots_table_is_refused(tmp_path):
    empty = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(empty)) as connection:
        connection.execute("CREATE TABLE other (x)")

    with pytest.raises(backups.BackupError):
        backups.check_backup(empty)


def test_latest_is_the_newest_backup():
    two_backups()

    found = backups.find_backup("latest")

    assert found.name == "ai-tabs-2026-11-02.sqlite"


def test_unknown_date_lists_the_dates_that_exist():
    two_backups()

    result = runner.invoke(app, ["backup", "--restore", "2025-01-01", "--yes"])

    assert result.exit_code == 1
    assert "2026-11-02, 2026-11-01" in result.output


def test_answer_no_changes_nothing():
    two_backups()
    insert(datetime(2026, 11, 3, 8, 0, 0))

    result = runner.invoke(app, ["backup", "--restore", "2026-11-01"], input="n\n")

    assert result.exit_code == 1
    assert snapshot_ids(settings().database) == ["2026-11-01/10-00-00", "2026-11-02/10-00-00", "2026-11-03/08-00-00"]
    assert list(settings().backup_dir.glob("ai-tabs-before-restore-*")) == []


def test_restore_command_prints_the_safety_copy_and_the_count():
    two_backups()

    result = runner.invoke(app, ["backup", "--restore", "latest", "--yes"])

    assert result.exit_code == 0
    assert "ai-tabs-before-restore-" in result.output
    assert "Restored 2 snapshots" in result.output

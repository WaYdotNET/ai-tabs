"""The daily maintenance of the interval agent: the prune of old snapshots and the daily backup."""

from datetime import datetime

from factories import windows_with_tabs

from ai_tabs import backups, snapshot, store
from ai_tabs.config import settings, write_config

NO_CHANGES = {"opened": [], "closed": [], "changed": []}
OLD = datetime(2026, 9, 1, 10, 0, 0)
RECENT = datetime(2026, 11, 2, 6, 0, 0)


def insert(moment: datetime) -> str:
    """Store a snapshot with one shell tab at a moment and return its ID."""
    return store.insert_snapshot(windows_with_tabs(1), NO_CHANGES, moment)


def snapshot_ids() -> list[str]:
    """Return the IDs of the snapshots in the live database, newest first."""
    return [summary.id for summary in store.summaries()]


def test_due_maintenance_prunes_the_old_snapshots_and_writes_the_backup():
    insert(OLD)
    recent = insert(RECENT)

    snapshot.maintain(datetime(2026, 11, 2, 9, 10, 0))

    assert snapshot_ids() == [recent]
    assert (settings().backup_dir / "ai-tabs-2026-11-02.sqlite").exists()


def test_the_daily_backup_holds_the_pruned_database():
    insert(OLD)
    insert(RECENT)

    snapshot.maintain(datetime(2026, 11, 2, 9, 10, 0))

    assert backups.snapshot_count(settings().backup_dir / "ai-tabs-2026-11-02.sqlite") == 1


def test_maintenance_before_the_first_backup_time_prunes_nothing():
    write_config({"backup_times": ["07:30", "17:00"]})
    old = insert(OLD)
    recent = insert(RECENT)

    snapshot.maintain(datetime(2026, 11, 2, 7, 0, 0))

    assert snapshot_ids() == [recent, old]
    assert settings().backup_dir.exists() is False


def test_maintenance_after_the_backup_of_the_slot_prunes_nothing():
    old = insert(OLD)
    recent = insert(RECENT)
    store.daily_backup(datetime(2026, 11, 2, 9, 5, 0))

    snapshot.maintain(datetime(2026, 11, 2, 9, 10, 0))

    assert snapshot_ids() == [recent, old]


def test_maintenance_at_the_17_00_slot_prunes_again():
    insert(OLD)
    recent = insert(RECENT)
    store.daily_backup(datetime(2026, 11, 2, 9, 5, 0))

    snapshot.maintain(datetime(2026, 11, 2, 17, 5, 0))

    assert snapshot_ids() == [recent]

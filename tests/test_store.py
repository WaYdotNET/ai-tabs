"""The snapshot database: storage, pins, the recommended snapshot, pruning and backups."""

import os
from datetime import date, datetime

from factories import windows_with_tabs

from ai_tabs import backups, store
from ai_tabs.config import settings, write_config

NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def insert(moment: datetime, tabs: int) -> str:
    """Store a snapshot with `tabs` shell tabs at a moment and return its ID."""
    return store.insert_snapshot(windows_with_tabs(tabs), NO_CHANGES, moment)


def backup_names() -> list[str]:
    """Return the names of the files in the backup folder, sorted."""
    return sorted(path.name for path in settings().backup_dir.iterdir())


def test_latest_snapshot_is_the_newest_with_its_counts():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=3)
    insert(datetime(2026, 11, 2, 11, 0, 0), tabs=5)

    latest = store.find_snapshot(store.LATEST)

    assert latest.summary.id == "2026-11-02/11-00-00"
    assert (latest.summary.tabs, latest.summary.agents) == (5, 0)
    assert len(latest.windows[0].tabs) == 5


def test_unknown_snapshot_id_finds_nothing():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=1)

    assert store.find_snapshot("2026-11-02/09-00-00") is None


def test_recommended_is_the_newest_when_nothing_is_pinned():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=11)
    insert(datetime(2026, 11, 2, 11, 0, 0), tabs=1)

    assert store.recommended_id() == "2026-11-02/11-00-00"


def test_recommended_is_the_crash_pin_while_newer_snapshots_hold_fewer_tabs():
    before_crash = insert(datetime(2026, 11, 2, 21, 48, 18), tabs=11)
    insert(datetime(2026, 11, 2, 22, 5, 40), tabs=1)
    insert(datetime(2026, 11, 2, 22, 10, 42), tabs=2)
    store.set_pin(before_crash, "before-drop")

    assert store.recommended_id() == before_crash


def test_recommended_is_the_newest_once_the_tabs_are_restored():
    before_crash = insert(datetime(2026, 11, 2, 21, 48, 18), tabs=11)
    insert(datetime(2026, 11, 2, 22, 5, 40), tabs=1)
    insert(datetime(2026, 11, 2, 22, 26, 26), tabs=13)
    store.set_pin(before_crash, "before-drop")

    assert store.recommended_id() == "2026-11-02/22-26-26"


def test_a_manual_pin_does_not_change_the_recommended_snapshot():
    pinned = insert(datetime(2026, 11, 2, 10, 0, 0), tabs=11)
    insert(datetime(2026, 11, 2, 11, 0, 0), tabs=1)
    store.set_pin(pinned, "manual")

    assert store.recommended_id() == "2026-11-02/11-00-00"


def test_pin_of_an_unknown_id_reports_false():
    assert store.set_pin("2026-11-02/10-00-00", "manual") is False


def test_prune_deletes_old_snapshots_but_keeps_pinned_ones():
    old = insert(datetime(2026, 9, 1, 10, 0, 0), tabs=1)
    old_pinned = insert(datetime(2026, 9, 1, 11, 0, 0), tabs=1)
    recent = insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    store.set_pin(old_pinned, "manual")

    deleted = store.prune(date(2026, 11, 2))

    assert deleted == 1
    assert [summary.id for summary in store.summaries()] == [recent, old_pinned]
    assert store.find_snapshot(old) is None


def test_prune_keeps_the_newest_snapshot_however_old_it_is():
    only = insert(datetime(2026, 1, 1, 10, 0, 0), tabs=1)

    store.prune(date(2026, 11, 2))

    assert [summary.id for summary in store.summaries()] == [only]


def test_maintenance_is_not_due_before_the_first_backup_time():
    assert store.maintenance_due(datetime(2026, 11, 2, 8, 59, 59)) is False


def test_maintenance_is_due_at_9_10_when_the_day_has_no_backup():
    assert store.maintenance_due(datetime(2026, 11, 2, 9, 10, 0)) is True


def test_maintenance_follows_the_backup_times_of_the_configuration_file():
    write_config({"backup_times": ["07:30"]})

    assert store.maintenance_due(datetime(2026, 11, 2, 7, 30, 0)) is True


def test_maintenance_is_not_due_at_noon_after_the_9_00_run():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert store.maintenance_due(datetime(2026, 11, 2, 12, 0, 0)) is False


def test_maintenance_is_due_again_at_17_05_after_the_9_00_run():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert store.maintenance_due(datetime(2026, 11, 2, 17, 5, 0)) is True


def test_maintenance_is_not_due_in_the_evening_after_the_17_00_run():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 17, 5, 0))

    assert store.maintenance_due(datetime(2026, 11, 2, 23, 59, 0)) is False


def test_maintenance_is_due_at_9_00_on_the_day_after_the_17_00_run():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 17, 5, 0))

    assert store.maintenance_due(datetime(2026, 11, 3, 9, 0, 0)) is True


def test_an_old_backup_of_the_day_makes_the_maintenance_due():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    written = store.write_backup(date(2026, 11, 2))
    stamp = datetime(2026, 11, 2, 8, 59, 0).timestamp()
    os.utime(written, (stamp, stamp))

    assert store.maintenance_due(datetime(2026, 11, 2, 9, 10, 0)) is True


def test_unchanged_data_at_the_17_00_slot_keeps_the_file_of_the_day():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    first = store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))
    inode = first.stat().st_ino

    second = store.daily_backup(datetime(2026, 11, 2, 17, 5, 0))

    assert backup_names() == ["ai-tabs-2026-11-02.sqlite"]
    assert second.stat().st_ino == inode


def test_unchanged_data_at_the_17_00_slot_gives_the_file_the_time_of_now():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    written = store.daily_backup(datetime(2026, 11, 2, 17, 5, 0))

    assert written.stat().st_mtime == datetime(2026, 11, 2, 17, 5, 0).timestamp()


def test_unchanged_data_the_next_morning_renames_the_backup_of_yesterday():
    insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 1, 17, 5, 0))

    written = store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert written.name == "ai-tabs-2026-11-02.sqlite"
    assert backup_names() == ["ai-tabs-2026-11-02.sqlite"]
    assert backups.snapshot_count(written) == 1


def test_a_renamed_backup_closes_the_slot():
    insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 1, 17, 5, 0))

    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert store.maintenance_due(datetime(2026, 11, 2, 9, 15, 0)) is False


def test_changed_data_writes_a_new_backup():
    insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    store.write_backup(date(2026, 11, 1))
    insert(datetime(2026, 11, 1, 11, 0, 0), tabs=2)

    written = store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert backup_names() == ["ai-tabs-2026-11-01.sqlite", "ai-tabs-2026-11-02.sqlite"]
    assert backups.snapshot_count(written) == 2


def test_changed_data_at_the_17_00_slot_replaces_the_file_of_the_day():
    insert(datetime(2026, 11, 2, 8, 0, 0), tabs=1)
    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))
    insert(datetime(2026, 11, 2, 12, 0, 0), tabs=2)

    written = store.daily_backup(datetime(2026, 11, 2, 17, 5, 0))

    assert backup_names() == ["ai-tabs-2026-11-02.sqlite"]
    assert backups.snapshot_count(written) == 2


def test_a_changed_pin_counts_as_changed_data():
    pinned = insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    store.write_backup(date(2026, 11, 1))
    store.set_pin(pinned, "manual")

    store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert backup_names() == ["ai-tabs-2026-11-01.sqlite", "ai-tabs-2026-11-02.sqlite"]


def test_an_unreadable_newest_backup_counts_as_changed_data():
    insert(datetime(2026, 11, 1, 10, 0, 0), tabs=1)
    settings().backup_dir.mkdir(parents=True)
    (settings().backup_dir / "ai-tabs-2026-11-01.sqlite").write_text("not a database")

    written = store.daily_backup(datetime(2026, 11, 2, 9, 10, 0))

    assert backup_names() == ["ai-tabs-2026-11-01.sqlite", "ai-tabs-2026-11-02.sqlite"]
    assert backups.snapshot_count(written) == 1


def test_only_the_newest_backups_stay():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=1)
    for day in range(1, 10):
        store.write_backup(date(2026, 11, day))

    kept = sorted(path.name for path in settings().backup_dir.iterdir())

    assert kept == [f"ai-tabs-2026-11-{day:02}.sqlite" for day in range(3, 10)]

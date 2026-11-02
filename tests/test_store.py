"""The snapshot database: storage, pins, the recommended snapshot, pruning and backups."""

from datetime import date, datetime

from factories import windows_with_tabs

from ai_tabs import store
from ai_tabs.config import settings

NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def insert(moment: datetime, tabs: int) -> str:
    """Store a snapshot with `tabs` shell tabs at a moment and return its ID."""
    return store.insert_snapshot(windows_with_tabs(tabs), NO_CHANGES, moment)


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


def test_a_backup_is_written_once_a_day():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=1)

    first = store.backup_if_due(date(2026, 11, 2))
    second = store.backup_if_due(date(2026, 11, 2))

    assert first.name == "ai-tabs-2026-11-02.sqlite"
    assert first.exists()
    assert second is None


def test_only_the_newest_backups_stay():
    insert(datetime(2026, 11, 2, 10, 0, 0), tabs=1)
    for day in range(1, 10):
        store.write_backup(date(2026, 11, day))

    kept = sorted(path.name for path in settings().backup_dir.iterdir())

    assert kept == [f"ai-tabs-2026-11-{day:02}.sqlite" for day in range(3, 10)]

"""Recording snapshots: change detection, automatic pins and the Markdown views."""

from datetime import datetime

from factories import agent_pane, sized_window, tab, windows_with_tabs

from ai_tabs import snapshot, store
from ai_tabs.config import write_config
from ai_tabs.models import Window

BOOT = datetime(2026, 11, 2, 9, 0, 0)


def summary(created_at: datetime, tabs: int) -> store.Summary:
    """Return a summary of an unpinned snapshot with `tabs` tabs."""
    return store.Summary("id", created_at, tabs, 0, 0, 0, 0, None)


def test_last_snapshot_before_the_boot_gets_a_boot_pin():
    previous = summary(datetime(2026, 11, 2, 8, 55, 0), tabs=3)

    assert snapshot.auto_pin_reason(previous, windows_with_tabs(3), BOOT) == "before-boot"


def test_losing_more_than_half_of_the_tabs_gets_a_crash_pin():
    previous = summary(datetime(2026, 11, 2, 10, 0, 0), tabs=11)

    assert snapshot.auto_pin_reason(previous, windows_with_tabs(1), BOOT) == "before-drop"


def test_losing_exactly_half_of_the_tabs_is_not_a_crash():
    previous = summary(datetime(2026, 11, 2, 10, 0, 0), tabs=10)

    assert snapshot.auto_pin_reason(previous, windows_with_tabs(5), BOOT) is None


def test_closing_the_only_tab_is_not_a_crash():
    previous = summary(datetime(2026, 11, 2, 10, 0, 0), tabs=1)

    assert snapshot.auto_pin_reason(previous, windows_with_tabs(0), BOOT) is None


def test_same_windows_write_no_new_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    snapshot.record_snapshot(windows_with_tabs(2), datetime(2026, 11, 2, 10, 0, 0))

    assert snapshot.record_snapshot(windows_with_tabs(2), datetime(2026, 11, 2, 10, 5, 0)) == snapshot.UNCHANGED
    assert len(store.summaries()) == 1


def test_first_snapshot_after_a_boot_pins_the_one_before(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    before = snapshot.record_snapshot(windows_with_tabs(4), datetime(2026, 11, 2, 8, 50, 0)).snapshot_id

    snapshot.record_snapshot(windows_with_tabs(1), datetime(2026, 11, 2, 9, 1, 0))

    assert store.find_snapshot(before).summary.pinned == "before-boot"


def test_a_manual_pin_is_not_replaced_by_an_automatic_one(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    before = snapshot.record_snapshot(windows_with_tabs(4), datetime(2026, 11, 2, 10, 0, 0)).snapshot_id
    store.set_pin(before, "manual")

    snapshot.record_snapshot(windows_with_tabs(1), datetime(2026, 11, 2, 10, 5, 0))

    assert store.find_snapshot(before).summary.pinned == "manual"


def test_export_latest_rewrites_latest_md_after_every_new_snapshot(monkeypatch, isolated_data):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    write_config({"export_dir": str(isolated_data / "vault"), "export_latest": True})
    first = [Window([0, 0, 800, 600], [tab(agent_pane("s1", "Fix the build"), title="BUILD"), tab(agent_pane("s2"))])]
    snapshot.record_snapshot(first, datetime(2026, 11, 2, 10, 0, 0))

    snapshot.record_snapshot(windows_with_tabs(0), datetime(2026, 11, 2, 10, 5, 0))

    latest = (isolated_data / "vault/latest.md").read_text()
    assert "id: 2026-11-02/10-05-00" in latest
    assert "- Closed: **BUILD**: omp “Fix the build” in `/work`" in latest
    assert sorted(path.name for path in (isolated_data / "vault").iterdir()) == ["latest.md"]


def test_no_markdown_is_written_by_default(monkeypatch, isolated_data):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)

    snapshot.record_snapshot(windows_with_tabs(1), datetime(2026, 11, 2, 10, 0, 0))

    assert list(isolated_data.rglob("*.md")) == []


def test_pane_columns_that_change_with_the_same_frame_update_the_latest_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    snapshot.record_snapshot([sized_window([0, 0, 800, 600], 94, 25)], datetime(2026, 11, 2, 10, 0, 0))

    recorded = snapshot.record_snapshot([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 2, 10, 0, 15))

    latest = store.latest_snapshot()
    assert recorded == snapshot.Recorded(snapshot.Outcome.UPDATED, "2026-11-02/10-00-00")
    assert (len(store.summaries()), latest.summary.id, latest.windows) == (
        1, "2026-11-02/10-00-00", [sized_window([0, 0, 800, 600], 96, 25)])


def test_an_update_in_place_rewrites_latest_md(monkeypatch, isolated_data):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    write_config({"export_dir": str(isolated_data / "vault"), "export_latest": True})
    snapshot.record_snapshot([sized_window([0, 0, 800, 600], 94, 25)], datetime(2026, 11, 2, 10, 0, 0))
    (isolated_data / "vault/latest.md").unlink()

    snapshot.record_snapshot([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 2, 10, 0, 15))

    assert "id: 2026-11-02/10-00-00" in (isolated_data / "vault/latest.md").read_text()


def test_a_frame_only_change_updates_the_latest_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    snapshot.store_if_changed(windows_with_tabs(2), datetime(2026, 11, 2, 10, 0, 0))
    moved = [Window([40, 20, 1200, 900], windows_with_tabs(2)[0].tabs)]

    recorded = snapshot.store_if_changed(moved, datetime(2026, 11, 2, 10, 5, 0))

    assert (recorded.outcome, len(store.summaries()), store.latest_snapshot().windows) == (
        snapshot.Outcome.UPDATED, 1, moved)


def test_a_size_change_of_a_pinned_snapshot_adds_a_new_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    first = snapshot.record_snapshot([sized_window([0, 0, 800, 600], 94, 25)], datetime(2026, 11, 2, 10, 0, 0))
    store.set_pin(first.snapshot_id, "manual")

    recorded = snapshot.record_snapshot([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 2, 10, 0, 15))

    assert (recorded.outcome, len(store.summaries()), store.find_snapshot(first.snapshot_id).windows) == (
        snapshot.Outcome.WROTE, 2, [sized_window([0, 0, 800, 600], 94, 25)])


def test_a_size_change_after_a_boot_adds_a_new_snapshot_and_pins_the_one_before(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    first = snapshot.record_snapshot([sized_window([0, 0, 800, 600], 94, 25)], datetime(2026, 11, 2, 8, 50, 0))

    recorded = snapshot.record_snapshot([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 2, 9, 1, 0))

    assert (recorded.outcome, len(store.summaries()), store.find_snapshot(first.snapshot_id).summary.pinned) == (
        snapshot.Outcome.WROTE, 2, "before-boot")


def test_an_opened_tab_adds_a_new_snapshot(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    snapshot.record_snapshot(windows_with_tabs(2), datetime(2026, 11, 2, 10, 0, 0))

    recorded = snapshot.record_snapshot(windows_with_tabs(3), datetime(2026, 11, 2, 10, 5, 0))

    assert (recorded, len(store.summaries())) == (snapshot.Recorded(snapshot.Outcome.WROTE, "2026-11-02/10-05-00"), 2)


def test_the_log_line_of_an_update_in_place_says_sizes_only(monkeypatch, capsys):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    snapshot.record_snapshot([sized_window([0, 0, 800, 600], 94, 25)], datetime(2026, 11, 2, 10, 0, 0))

    snapshot.log_snapshot([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 2, 10, 0, 15), "test: ")

    assert capsys.readouterr().out == "test: 10:00:15 Updated snapshot 2026-11-02/10-00-00 (sizes only) (1 panes)\n"

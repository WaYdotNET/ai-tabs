"""Recording snapshots: change detection, automatic pins and the Markdown views."""

from datetime import datetime

from factories import agent_pane, tab, windows_with_tabs

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

    assert snapshot.record_snapshot(windows_with_tabs(2), datetime(2026, 11, 2, 10, 5, 0)) is None
    assert len(store.summaries()) == 1


def test_first_snapshot_after_a_boot_pins_the_one_before(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    before = snapshot.record_snapshot(windows_with_tabs(4), datetime(2026, 11, 2, 8, 50, 0))

    snapshot.record_snapshot(windows_with_tabs(1), datetime(2026, 11, 2, 9, 1, 0))

    assert store.find_snapshot(before).summary.pinned == "before-boot"


def test_a_manual_pin_is_not_replaced_by_an_automatic_one(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: BOOT)
    before = snapshot.record_snapshot(windows_with_tabs(4), datetime(2026, 11, 2, 10, 0, 0))
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

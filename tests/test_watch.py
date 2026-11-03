"""The watcher: debounce of layout events, its launchd agent, and the lock of the two snapshot writers."""

import asyncio
import plistlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from factories import shell_pane, tab, windows_with_tabs

from ai_tabs import cli, snapshot, store, watch
from ai_tabs.config import LAUNCHCTL, write_config
from ai_tabs.models import Pane, Window
from ai_tabs.watch import Debouncer, same_except_resize

QUIET = 0.05
GAP = 0.3


async def burst(debouncer: Debouncer, events: int, spacing: float) -> None:
    """Poke the debouncer `events` times, `spacing` seconds apart."""
    for _ in range(events):
        debouncer.poke()
        await asyncio.sleep(spacing)


def actions_after(bursts: list[tuple[int, float]]) -> int:
    """Send bursts of (events, spacing) with GAP seconds of quiet after each. Return how many times the action ran."""
    calls = []

    async def action() -> None:
        calls.append(time.monotonic())

    async def drive() -> None:
        debouncer = Debouncer(action, QUIET)
        worker = asyncio.create_task(debouncer.run())
        for events, spacing in bursts:
            await burst(debouncer, events, spacing)
            await asyncio.sleep(GAP)
        worker.cancel()

    asyncio.run(drive())
    return len(calls)


def test_a_burst_longer_than_the_quiet_time_runs_the_action_once():
    assert actions_after([(10, QUIET / 2)]) == 1


def test_two_bursts_far_apart_run_the_action_twice():
    assert actions_after([(5, 0.01), (5, 0.01)]) == 2


def test_no_event_runs_no_action():
    assert actions_after([(0, 0.01)]) == 0


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    """Put the launchd files and the tool under a fake home, and record the launchctl calls."""
    calls = []

    def fake_run(command, **_options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("HOME", "/Users/tester")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/Users/tester/.local/bin/{name}")
    monkeypatch.setattr(cli.os, "getuid", lambda: 501)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "LAUNCHD_LOG", Path("/Users/tester/Library/Logs/ai-tabs.log"))
    monkeypatch.setattr(cli, "LAUNCHD_PLIST", tmp_path / "agents/snapshot.plist")
    monkeypatch.setattr(cli, "WATCH_LAUNCHD_PLIST", tmp_path / "agents/watch.plist")
    return calls


def test_the_watch_agent_runs_ai_tabs_watch_and_starts_again_after_30_seconds(fake_home):
    plist = plistlib.loads(cli.launchd_plist(cli.watch_agent()).encode())

    assert plist == {
        "Label": "com.github.ai-tabs.watch",
        "ProgramArguments": ["/Users/tester/.local/bin/ai-tabs", "watch"],
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "RunAtLoad": True,
        "EnvironmentVariables": {"PATH": "/Users/tester/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": "/Users/tester/Library/Logs/ai-tabs.log",
        "StandardErrorPath": "/Users/tester/Library/Logs/ai-tabs.log",
    }


def test_the_snapshot_agent_keeps_its_interval(fake_home):
    plist = plistlib.loads(cli.launchd_plist(cli.snapshot_agent()).encode())

    assert (plist["Label"], plist["ProgramArguments"], plist["StartInterval"], "KeepAlive" in plist) == (
        "com.github.ai-tabs.snapshot", ["/Users/tester/.local/bin/ai-tabs", "snapshot"], 300, False)


def test_install_loads_both_agents_by_default(fake_home, tmp_path):
    cli.install()

    loaded = [command for command in fake_home if command[1] == "bootstrap"]
    assert loaded == [
        [LAUNCHCTL, "bootstrap", "gui/501", str(tmp_path / "agents/snapshot.plist")],
        [LAUNCHCTL, "bootstrap", "gui/501", str(tmp_path / "agents/watch.plist")],
    ]


def test_install_without_watch_loads_only_the_snapshot_agent(fake_home, tmp_path):
    write_config({"watch": False})

    cli.install()

    loaded = [command for command in fake_home if command[1] == "bootstrap"]
    assert loaded == [[LAUNCHCTL, "bootstrap", "gui/501", str(tmp_path / "agents/snapshot.plist")]]


def test_install_without_watch_stops_and_deletes_an_old_watch_agent(fake_home, tmp_path):
    old_plist = tmp_path / "agents/watch.plist"
    old_plist.parent.mkdir(parents=True)
    old_plist.write_text("old")
    write_config({"watch": False})

    cli.install()

    stopped = [LAUNCHCTL, "bootout", "gui/501/com.github.ai-tabs.watch"] in fake_home
    assert (stopped, old_plist.exists()) == (True, False)


def test_uninstall_stops_and_deletes_both_agents(fake_home, tmp_path):
    cli.install()

    cli.uninstall()

    stopped = [command[2] for command in fake_home[-2:]]
    assert (stopped, list((tmp_path / "agents").iterdir())) == (
        ["gui/501/com.github.ai-tabs.snapshot", "gui/501/com.github.ai-tabs.watch"], [])


def test_a_second_writer_waits_for_the_lock_and_then_finds_no_change(monkeypatch):
    monkeypatch.setattr(snapshot, "boot_time", lambda: None)
    windows = windows_with_tabs(2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with snapshot.snapshot_lock():
            second = pool.submit(snapshot.record_snapshot, windows, datetime(2026, 11, 3, 10, 0, 1))
            time.sleep(0.2)
            waited = not second.done()
            snapshot.store_if_changed(windows, datetime(2026, 11, 3, 10, 0, 0))
        second_id = second.result(timeout=5)

    assert (waited, second_id, len(store.summaries())) == (True, None, 1)


def sized_window(frame: list[float], columns: int, rows: int) -> Window:
    """Return one window with one shell tab, whose pane has the size `columns` x `rows`."""
    return Window(frame, [tab(Pane("zsh", "/dev/ttys001", "/work", columns=columns, rows=rows))])


def test_windows_that_differ_only_in_frames_count_as_the_same():
    old = [Window([0, 0, 800, 600], [tab(shell_pane(), title="build")])]
    new = [Window([40, 20, 1200, 900], [tab(shell_pane(), title="build")])]

    assert same_except_resize(old, new) is True


def test_a_resize_that_changes_the_frame_and_the_pane_sizes_counts_as_the_same():
    old = [sized_window([0, 0, 800, 600], 96, 25)]
    new = [sized_window([0, 0, 400, 300], 46, 14)]

    assert same_except_resize(old, new) is True


def test_a_divider_drag_with_the_same_frame_counts_as_a_change():
    old = [sized_window([0, 0, 800, 600], 96, 25)]
    new = [sized_window([0, 0, 800, 600], 46, 25)]

    assert same_except_resize(old, new) is False


def test_a_different_tab_title_counts_as_a_change():
    old = [Window([0, 0, 800, 600], [tab(shell_pane(), title="build")])]
    new = [Window([0, 0, 800, 600], [tab(shell_pane(), title="deploy")])]

    assert same_except_resize(old, new) is False


def test_a_resize_with_a_different_tab_title_counts_as_a_change():
    old = [Window([0, 0, 800, 600], [tab(shell_pane(), title="build")])]
    new = [Window([0, 0, 400, 300], [tab(shell_pane(), title="deploy")])]

    assert same_except_resize(old, new) is False


def test_an_added_window_counts_as_a_change():
    old = [Window([0, 0, 800, 600], [tab(shell_pane())])]
    new = [*old, Window([0, 0, 800, 600], [tab(shell_pane("/dev/ttys009"))])]

    assert same_except_resize(old, new) is False


@pytest.fixture
def read_by_watcher(monkeypatch):
    """Replace the iTerm2 read of the watcher. Return a function that sets the windows of the next read."""
    monkeypatch.setattr(snapshot, "boot_time", lambda: None)
    current: list[list[Window]] = []

    async def fake_read(_connection):
        return current[-1]

    monkeypatch.setattr(watch, "read_windows", fake_read)
    return current.append


def test_the_watcher_stores_nothing_when_a_window_only_changes_its_size(read_by_watcher, capsys):
    snapshot.store_if_changed([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 3, 10, 0, 0))
    read_by_watcher([sized_window([100, 50, 400, 300], 46, 14)])

    asyncio.run(watch.logged_snapshot(None))

    assert (len(store.summaries()), capsys.readouterr().out.endswith("No change (frame only)\n")) == (1, True)


def test_the_watcher_stores_a_snapshot_after_a_divider_drag(read_by_watcher):
    snapshot.store_if_changed([sized_window([0, 0, 800, 600], 96, 25)], datetime(2026, 11, 3, 10, 0, 0))
    read_by_watcher([sized_window([0, 0, 800, 600], 46, 25)])

    asyncio.run(watch.logged_snapshot(None))

    assert len(store.summaries()) == 2


def test_the_watcher_stores_a_snapshot_when_a_tab_opens(read_by_watcher, capsys):
    snapshot.store_if_changed(windows_with_tabs(2), datetime(2026, 11, 3, 10, 0, 0))
    read_by_watcher(windows_with_tabs(3))

    asyncio.run(watch.logged_snapshot(None))

    assert (len(store.summaries()), "Wrote snapshot" in capsys.readouterr().out) == (2, True)


def test_the_watcher_stores_the_first_snapshot_when_the_history_is_empty(read_by_watcher):
    read_by_watcher(windows_with_tabs(1))

    asyncio.run(watch.logged_snapshot(None))

    assert len(store.summaries()) == 1

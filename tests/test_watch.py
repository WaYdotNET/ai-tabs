"""The watcher: debounce of layout events, its launchd agent, and the lock of the two snapshot writers."""

import asyncio
import plistlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from factories import windows_with_tabs

from ai_tabs import cli, snapshot, store
from ai_tabs.config import LAUNCHCTL, write_config
from ai_tabs.watch import Debouncer

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

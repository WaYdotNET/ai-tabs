"""The checks of `ai-tabs doctor`, one by one, and the exit code of the command."""

import asyncio
import os
import plistlib
from datetime import date, datetime
from types import SimpleNamespace

import iterm2
import pytest
from factories import windows_with_tabs
from typer.testing import CliRunner

from ai_tabs import cli, config, doctor, store
from ai_tabs.config import settings
from ai_tabs.doctor import FAIL, OK, WARN, Check, LaunchAgent
from ai_tabs.models import Agent

NO_CHANGES = {"opened": [], "closed": [], "changed": []}
NOW = datetime(2026, 11, 3, 10, 0, 0)
PROGRAM = "/Users/me/.local/bin/ai-tabs"
LOADED = "\tstate = not running\n\tprogram = /Users/me/.local/bin/ai-tabs\n\tlast exit code = 0\n"


def fake_connection() -> SimpleNamespace:
    """Return a connection whose websocket closes without iTerm2."""
    async def close() -> None:
        return None
    return SimpleNamespace(websocket=SimpleNamespace(close=close))


def fake_app(*session_ids: str) -> SimpleNamespace:
    """Return an iTerm2 app with one window and one tab that holds the sessions."""
    sessions = [SimpleNamespace(session_id=session_id) for session_id in session_ids]
    return SimpleNamespace(terminal_windows=[SimpleNamespace(tabs=[SimpleNamespace(sessions=sessions)])])


def use_app(monkeypatch, app: SimpleNamespace, prompts: dict[str, object]) -> None:
    """Make the iTerm2 API return the app, and the last prompt of each session from `prompts`."""
    async def get_app(connection):
        return app

    async def get_last_prompt(connection, session_id):
        return prompts.get(session_id)

    monkeypatch.setattr(iterm2, "async_get_app", get_app)
    monkeypatch.setattr(iterm2, "async_get_last_prompt", get_last_prompt)


def use_connection(monkeypatch, create) -> None:
    """Replace the connection to the iTerm2 Python API with `create`."""
    monkeypatch.setattr(iterm2.Connection, "async_create", create)


def write_plist(path, program: str) -> None:
    """Write a launchd plist that runs a program."""
    path.write_bytes(plistlib.dumps({"Label": "test", "ProgramArguments": [program, "snapshot"]}))


def agent_at(tmp_path, missing: str) -> LaunchAgent:
    """Return a launchd agent with its plist in the temporary folder."""
    return LaunchAgent("Snapshot agent", "com.github.ai-tabs.snapshot", tmp_path / "agent.plist", missing)


def insert(moment: datetime) -> str:
    """Store a snapshot with one shell tab at a moment and return its ID."""
    return store.insert_snapshot(windows_with_tabs(1), NO_CHANGES, moment)


def write_log(path, text: str, moment: datetime) -> None:
    """Write the launchd log and give it the modification time of a moment."""
    path.write_text(text)
    os.utime(path, (moment.timestamp(), moment.timestamp()))


def touch_backup(day: str) -> None:
    """Create an empty backup file of a day in `backup_dir`."""
    settings().backup_dir.mkdir(parents=True, exist_ok=True)
    (settings().backup_dir / f"ai-tabs-{day}.sqlite").write_bytes(b"")


def use_processes(monkeypatch, processes: list[tuple[str, int]], ttys: dict[str, str], sessions: set[str]) -> None:
    """Fake `ps`: the agent processes, the tty of each PID, and the ttys where `find_agent` finds a session."""
    monkeypatch.setattr(doctor, "agent_processes", lambda *arguments: processes)
    monkeypatch.setattr(doctor, "run", lambda *command: ttys.get(command[-1], ""))
    found = Agent("omp", 1, "/work", "id1", "work", "omp --resume id1")
    monkeypatch.setattr(doctor, "find_agent", lambda tty: found if tty in sessions else None)


def test_iterm_check_is_ok_when_iterm_runs(monkeypatch):
    monkeypatch.setattr(doctor, "iterm_is_running", lambda: True)

    assert doctor.iterm_running_check() == Check("iTerm2", OK, "iTerm2 runs")


def test_iterm_check_fails_when_iterm_does_not_run(monkeypatch):
    monkeypatch.setattr(doctor, "iterm_is_running", lambda: False)

    assert doctor.iterm_running_check() == Check("iTerm2", FAIL, "iTerm2 does not run")


def test_iterm_checks_do_not_connect_when_iterm_does_not_run(monkeypatch):
    monkeypatch.setattr(doctor, "iterm_is_running", lambda: False)
    use_connection(monkeypatch, lambda: pytest.fail("connected to iTerm2"))

    checks = doctor.iterm_checks()

    assert checks == [Check("iTerm2", FAIL, "iTerm2 does not run"),
                      Check("Python API", FAIL, "not checked: iTerm2 does not run"),
                      Check("Shell integration", WARN, "not checked: no connection to the Python API")]


def test_api_check_is_ok_when_iterm_answers(monkeypatch):
    async def create():
        return fake_connection()
    use_connection(monkeypatch, create)
    use_app(monkeypatch, fake_app("s1"), {"s1": object()})

    checks = asyncio.run(doctor.api_checks())

    assert checks == [Check("Python API", OK, "iTerm2 answers"),
                      Check("Shell integration", OK, "1 of 1 sessions have a prompt")]


def test_api_check_fails_with_the_settings_hint_when_the_connection_is_refused(monkeypatch):
    async def create():
        raise ConnectionRefusedError("Problem connecting to iTerm2")
    use_connection(monkeypatch, create)

    checks = asyncio.run(doctor.api_checks())

    assert checks == [
        Check("Python API", FAIL, "connection refused: iTerm2 > Settings > General > Magic > Enable Python API"),
        Check("Shell integration", WARN, "not checked: no connection to the Python API"),
    ]


def test_api_check_fails_when_iterm_does_not_answer_in_time(monkeypatch):
    async def create():
        await asyncio.sleep(1)
    use_connection(monkeypatch, create)
    monkeypatch.setattr(doctor, "API_TIMEOUT", 0.01)

    checks = asyncio.run(doctor.api_checks())

    assert checks[0] == Check("Python API", FAIL,
                              "no answer in 0.01 s: iTerm2 > Settings > General > Magic > Enable Python API")


def test_closing_the_connection_stops_its_message_reader():
    async def close_with_a_reader() -> bool:
        reader = asyncio.ensure_future(asyncio.sleep(60))
        await doctor.close_connection(fake_connection())
        return reader.cancelled()

    assert asyncio.run(close_with_a_reader()) is True


def test_shell_integration_warns_when_no_session_has_a_prompt(monkeypatch):
    use_app(monkeypatch, fake_app("s1", "s2"), {})

    check = asyncio.run(doctor.shell_integration_check(fake_connection()))

    assert check == Check("Shell integration", WARN, "no prompt in 2 sessions: restore cannot wait for the prompt. "
                                                     "Install the iTerm2 shell integration.")


def test_shell_integration_counts_a_failed_prompt_request_as_no_prompt(monkeypatch):
    use_app(monkeypatch, fake_app("s1", "s2"), {"s1": object()})

    async def get_last_prompt(connection, session_id):
        if session_id == "s2":
            raise iterm2.RPCException("SESSION_NOT_FOUND")
        return object()
    monkeypatch.setattr(iterm2, "async_get_last_prompt", get_last_prompt)

    check = asyncio.run(doctor.shell_integration_check(fake_connection()))

    assert check == Check("Shell integration", OK, "1 of 2 sessions have a prompt")


def test_launch_agent_is_ok_when_loaded_with_exit_code_0_and_the_current_program(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, PROGRAM)
    monkeypatch.setattr(doctor, "run", lambda *command: LOADED)

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check == Check("Snapshot agent", OK, f"loaded, last exit code = 0, runs {PROGRAM}")


def test_launch_agent_asks_launchctl_for_its_label_in_the_user_domain(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, PROGRAM)
    commands = []
    monkeypatch.setattr(doctor, "run", lambda *command: commands.append(command) or LOADED)

    doctor.launch_agent_check(agent, PROGRAM)

    assert commands == [("/bin/launchctl", "print", f"gui/{os.getuid()}/com.github.ai-tabs.snapshot")]


def test_launch_agent_uses_the_missing_status_when_the_plist_does_not_exist(tmp_path):
    agent = agent_at(tmp_path, WARN)

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check == Check("Snapshot agent", WARN, f"not installed: {tmp_path / 'agent.plist'} does not exist")


def test_launch_agent_fails_when_launchctl_does_not_know_it(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, PROGRAM)
    monkeypatch.setattr(doctor, "run", lambda *command: "")

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check == Check("Snapshot agent", FAIL, "com.github.ai-tabs.snapshot is not loaded: install the agent again")


def test_launch_agent_fails_when_the_last_run_ended_with_an_error(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, PROGRAM)
    monkeypatch.setattr(doctor, "run", lambda *command: "\tlast exit code = 1\n")

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check == Check("Snapshot agent", FAIL, "last exit code = 1")


def test_launch_agent_accepts_an_agent_that_never_exited(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, PROGRAM)
    monkeypatch.setattr(doctor, "run", lambda *command: "\tstate = running\n\tlast exit code = (never exited)\n")

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check.status == OK


def test_launch_agent_warns_when_the_plist_runs_an_older_install_path(monkeypatch, tmp_path):
    agent = agent_at(tmp_path, FAIL)
    write_plist(agent.plist, "/opt/homebrew/bin/uvx")
    monkeypatch.setattr(doctor, "run", lambda *command: LOADED)

    check = doctor.launch_agent_check(agent, PROGRAM)

    assert check == Check("Snapshot agent", WARN,
                          f"the plist runs /opt/homebrew/bin/uvx, not {PROGRAM}: install the agent again")


def test_a_missing_watcher_is_a_warning(monkeypatch, tmp_path):
    missing = LaunchAgent("Watcher agent", "com.github.ai-tabs.watch", tmp_path / "watch.plist", WARN)
    monkeypatch.setattr(doctor, "WATCH_AGENT", missing)

    check = doctor.watch_agent_check(PROGRAM)

    assert check == Check("Watcher agent", WARN, f"not installed: {tmp_path / 'watch.plist'} does not exist")


def test_a_watcher_turned_off_in_the_settings_is_ok():
    config.write_config({"watch": False})

    check = doctor.watch_agent_check(PROGRAM)

    assert check == Check("Watcher agent", OK, "off: the watch setting is false")


def test_snapshot_age_fails_when_there_is_no_snapshot():
    assert doctor.snapshot_age_check(NOW) == Check("Last snapshot", FAIL, "no snapshot: run `ai-tabs snapshot`")


def test_snapshot_age_does_not_create_a_missing_database():
    doctor.snapshot_age_check(NOW)

    assert not settings().database.exists()


def test_snapshot_age_is_ok_for_a_recent_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "LAUNCHD_LOG", tmp_path / "missing.log")
    insert(datetime(2026, 11, 3, 9, 58, 0))

    check = doctor.snapshot_age_check(NOW)

    assert check == Check("Last snapshot", OK, "newest snapshot 2026-11-03/09-58-00 (2 min ago), last run 2 min ago")


def test_snapshot_age_warns_after_three_intervals_without_a_run(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "LAUNCHD_LOG", tmp_path / "missing.log")
    insert(datetime(2026, 11, 3, 9, 44, 0))

    check = doctor.snapshot_age_check(NOW)

    assert check == Check("Last snapshot", WARN,
                          "newest snapshot 2026-11-03/09-44-00 (16 min ago), last run 16 min ago")


def test_snapshot_age_counts_a_run_without_a_change(monkeypatch, tmp_path):
    log = tmp_path / "ai-tabs.log"
    monkeypatch.setattr(doctor, "LAUNCHD_LOG", log)
    write_log(log, "08:00:00 Wrote snapshot 2026-11-03/08-00-00 (3 panes)\n09:58:00 No change (3 panes)\n",
              datetime(2026, 11, 3, 9, 58, 0))
    insert(datetime(2026, 11, 3, 8, 0, 0))

    check = doctor.snapshot_age_check(NOW)

    assert check == Check("Last snapshot", OK, "newest snapshot 2026-11-03/08-00-00 (2 h ago), last run 2 min ago")


def test_snapshot_age_ignores_a_log_that_ends_with_an_error(monkeypatch, tmp_path):
    log = tmp_path / "ai-tabs.log"
    monkeypatch.setattr(doctor, "LAUNCHD_LOG", log)
    write_log(log, "09:58:00 No change (3 panes)\nTraceback (most recent call last):\n",
              datetime(2026, 11, 3, 9, 58, 0))
    insert(datetime(2026, 11, 3, 8, 0, 0))

    check = doctor.snapshot_age_check(NOW)

    assert check.status == WARN


def test_age_text_uses_hours_from_two_hours():
    assert doctor.age_text(datetime(2026, 11, 3, 12, 0, 0) - datetime(2026, 11, 3, 9, 30, 0)) == "2 h"


def test_age_text_uses_days_from_two_days():
    assert doctor.age_text(datetime(2026, 11, 3, 12, 0, 0) - datetime(2026, 11, 1, 10, 0, 0)) == "2 d"


def test_database_check_is_ok_and_counts_the_snapshots():
    insert(datetime(2026, 11, 3, 9, 0, 0))
    insert(datetime(2026, 11, 3, 9, 5, 0))

    check = doctor.database_check()

    assert check == Check("Database", OK, f"integrity ok, 2 snapshots in {settings().database}")


def test_database_check_fails_when_the_database_does_not_exist():
    check = doctor.database_check()

    assert check == Check("Database", FAIL, f"{settings().database} does not exist")


def test_database_check_fails_when_the_file_is_not_a_database():
    settings().database.parent.mkdir(parents=True)
    settings().database.write_bytes(b"not a database" * 100)

    check = doctor.database_check()

    assert check == Check("Database", FAIL, f"{settings().database}: file is not a database")


def test_backup_check_is_ok_for_a_backup_of_two_days_ago():
    touch_backup("2026-10-30")
    touch_backup("2026-11-01")

    check = doctor.backup_check(date(2026, 11, 3))

    assert check == Check("Backups", OK, f"2 backups in {settings().backup_dir}, newest 2026-11-01 (2 d ago)")


def test_backup_check_warns_when_the_newest_backup_is_older_than_two_days():
    touch_backup("2026-10-31")

    check = doctor.backup_check(date(2026, 11, 3))

    assert check == Check("Backups", WARN, f"1 backups in {settings().backup_dir}, newest 2026-10-31 (3 d ago)")


def test_backup_check_warns_when_there_is_no_backup():
    check = doctor.backup_check(date(2026, 11, 3))

    assert check == Check("Backups", WARN, f"no backup in {settings().backup_dir}")


def test_agent_detection_is_ok_when_each_agent_tty_has_a_session(monkeypatch):
    use_processes(monkeypatch, [("omp", 11), ("claude", 12)], {"11": "ttys001\n", "12": "ttys002\n"},
                  {"ttys001", "ttys002"})

    check = doctor.agent_detection_check()

    assert check == Check("Agent detection", OK, "2 agent processes on a tty, each with a session")


def test_agent_detection_warns_for_an_agent_without_a_session(monkeypatch):
    use_processes(monkeypatch, [("omp", 11), ("omp", 12)], {"11": "ttys001\n", "12": "ttys002\n"}, {"ttys001"})

    check = doctor.agent_detection_check()

    assert check == Check("Agent detection", WARN, "no session found for: omp 12 on ttys002")


def test_agent_detection_skips_processes_without_a_tty(monkeypatch):
    use_processes(monkeypatch, [("omp", 11), ("claude", 12)], {"11": "ttys001\n", "12": "??\n"}, {"ttys001"})

    check = doctor.agent_detection_check()

    assert check == Check("Agent detection", OK, "1 agent processes on a tty, each with a session")


def test_agent_detection_asks_ps_for_the_tty_of_each_pid(monkeypatch):
    commands = []
    monkeypatch.setattr(doctor, "agent_processes", lambda *arguments: [("omp", 11)])
    monkeypatch.setattr(doctor, "run", lambda *command: commands.append(command) or "")

    doctor.agent_detection_check()

    assert commands == [("/bin/ps", "-o", "tty=", "-p", "11")]


def test_doctor_exits_with_1_when_a_check_fails(monkeypatch):
    monkeypatch.setattr(cli, "run_checks", lambda program: [Check("iTerm2", OK, "iTerm2 runs"),
                                                            Check("Database", FAIL, "broken")])

    result = CliRunner(env={"COLUMNS": "200"}).invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "broken" in result.output


def test_doctor_exits_with_0_when_no_check_fails(monkeypatch):
    monkeypatch.setattr(cli, "run_checks", lambda program: [Check("Backups", WARN, "no backup")])

    result = CliRunner(env={"COLUMNS": "200"}).invoke(cli.app, ["doctor"])

    assert result.exit_code == 0

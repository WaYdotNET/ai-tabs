"""Check what ai-tabs needs: iTerm2 and its Python API, the launchd agents, the data and the agent detection.

Each check is a small function that returns a `Check`, so that the checks can be tested one by one.
"""

import asyncio
import os
import plistlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import iterm2
from rich.markup import escape
from rich.table import Table
from websockets.exceptions import WebSocketException

from . import store
from .agents import agent_processes, find_agent
from .config import (
    LAUNCHCTL,
    LAUNCHD_LABEL,
    LAUNCHD_LOG,
    LAUNCHD_PLIST,
    PS,
    WATCH_LAUNCHD_LABEL,
    WATCH_LAUNCHD_PLIST,
    settings,
)
from .display import console
from .iterm import iterm_is_running
from .palette import Palette
from .system import run

OK, WARN, FAIL = "ok", "warn", "fail"

ITERM, API, SHELL = "iTerm2", "Python API", "Shell integration"
AGE, DATABASE, BACKUPS, DETECTION = "Last snapshot", "Database", "Backups", "Agent detection"

API_TIMEOUT = 5.0
API_HINT = "iTerm2 > Settings > General > Magic > Enable Python API"
NO_API = "not checked: no connection to the Python API"
STALE_RUNS = 3
BACKUP_MAX_AGE = timedelta(days=2)
# The same file names that `store.prune_backups` keeps.
BACKUP_GLOB = "ai-tabs-????-??-??.sqlite"
LOG_TAIL_BYTES = 4096
GOOD_EXIT_CODES = ("0", "(never exited)")
EXIT_CODE_RE = re.compile(r"^\s*last exit code = (.+)$", re.MULTILINE)
RUN_LINE_RE = re.compile(r"^\d\d:\d\d:\d\d (Wrote snapshot|No change)")
NO_TTY = ("", "?", "??")


@dataclass(frozen=True)
class Check:
    """The result of one check: its name, its status (`ok`, `warn` or `fail`) and what it found."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class LaunchAgent:
    """A launchd agent of ai-tabs, and the status of its check when its plist does not exist."""

    name: str
    label: str
    plist: Path
    missing: str


SNAPSHOT_AGENT = LaunchAgent("Snapshot agent", LAUNCHD_LABEL, LAUNCHD_PLIST, FAIL)
WATCH_AGENT = LaunchAgent("Watcher agent", WATCH_LAUNCHD_LABEL, WATCH_LAUNCHD_PLIST, WARN)


@dataclass(frozen=True)
class AgentProcess:
    """An omp or claude process and its tty."""

    kind: str
    pid: int
    tty: str


def iterm_running_check() -> Check:
    """Tell if iTerm2 runs. The check does not start iTerm2."""
    if iterm_is_running():
        return Check(ITERM, OK, "iTerm2 runs")
    return Check(ITERM, FAIL, "iTerm2 does not run")


async def has_prompt(connection: iterm2.Connection, session_id: str) -> bool:
    """Tell if iTerm2 knows the last prompt of a session. Only the shell integration records prompts."""
    try:
        prompt = await iterm2.async_get_last_prompt(connection, session_id)
    except iterm2.RPCException:
        return False
    return prompt is not None


async def shell_integration_check(connection: iterm2.Connection) -> Check:
    """Tell if at least one open session has a last prompt, so that restore can wait for the prompt."""
    app = await iterm2.async_get_app(connection)
    sessions = [session for window in app.terminal_windows for tab in window.tabs for session in tab.sessions]
    prompts = sum([await has_prompt(connection, session.session_id) for session in sessions])
    if prompts:
        return Check(SHELL, OK, f"{prompts} of {len(sessions)} sessions have a prompt")
    return Check(SHELL, WARN, f"no prompt in {len(sessions)} sessions: restore cannot wait for the prompt. "
                              "Install the iTerm2 shell integration.")


def no_api(detail: str) -> list[Check]:
    """Return the checks of the Python API when iTerm2 does not answer."""
    return [Check(API, FAIL, detail), Check(SHELL, WARN, NO_API)]


async def close_connection(connection: iterm2.Connection) -> None:
    """Stop the message reader of the connection, then close the websocket.

    The reader prints a traceback when the websocket closes under it. The checks run in their own
    event loop, so every other task in it belongs to the connection.
    """
    readers = asyncio.all_tasks() - {asyncio.current_task()}
    for reader in readers:
        reader.cancel()
    await asyncio.gather(*readers, return_exceptions=True)
    await connection.websocket.close()



async def api_checks() -> list[Check]:
    """Connect to the iTerm2 Python API and run the checks that need it, in one connection."""
    try:
        connection = await asyncio.wait_for(iterm2.Connection.async_create(), API_TIMEOUT)
    except TimeoutError:
        return no_api(f"no answer in {API_TIMEOUT:g} s: {API_HINT}")
    except OSError:
        return no_api(f"connection refused: {API_HINT}")
    except WebSocketException as error:
        return no_api(f"iTerm2 refused the script ({error}): allow ai-tabs when iTerm2 asks")
    try:
        return [Check(API, OK, "iTerm2 answers"), await shell_integration_check(connection)]
    finally:
        await close_connection(connection)


def iterm_checks() -> list[Check]:
    """Run the iTerm2 checks.

    The connection to the Python API starts iTerm2, so the API checks run only when iTerm2 runs.
    """
    running = iterm_running_check()
    if running.status != OK:
        return [running, *no_api("not checked: iTerm2 does not run")]
    return [running, *asyncio.run(api_checks())]


def plist_program(plist: Path) -> str:
    """Return the program that a launchd plist runs, or an empty string when the plist has none."""
    try:
        with plist.open("rb") as file:
            arguments = plistlib.load(file).get("ProgramArguments", [])
    except ValueError:
        return ""
    return arguments[0] if arguments else ""


def last_exit_code(label: str) -> str | None:
    """Return the last exit code that launchctl shows for an agent, or None when the agent is not loaded."""
    output = run(LAUNCHCTL, "print", f"gui/{os.getuid()}/{label}")
    if not output:
        return None
    match = EXIT_CODE_RE.search(output)
    return match.group(1).strip() if match else "(never exited)"


def program_check(agent: LaunchAgent, program: str) -> Check:
    """Tell if the plist of a loaded agent runs the current program. An older install path is a warning."""
    installed = plist_program(agent.plist)
    if installed != program:
        runs = installed or "nothing"
        return Check(agent.name, WARN, f"the plist runs {runs}, not {program}: install the agent again")
    return Check(agent.name, OK, f"loaded, last exit code = 0, runs {program}")


def launch_agent_check(agent: LaunchAgent, program: str) -> Check:
    """Tell if a launchd agent has its plist, is loaded, ended without an error and runs the current program."""
    if not agent.plist.exists():
        return Check(agent.name, agent.missing, f"not installed: {agent.plist} does not exist")
    code = last_exit_code(agent.label)
    if code is None:
        return Check(agent.name, FAIL, f"{agent.label} is not loaded: install the agent again")
    if code not in GOOD_EXIT_CODES:
        return Check(agent.name, FAIL, f"last exit code = {code}")
    return program_check(agent, program)


def last_line(path: Path) -> str:
    """Return the last line of a file. Only the end of the file is read, because the log only grows."""
    with path.open("rb") as file:
        file.seek(max(0, path.stat().st_size - LOG_TAIL_BYTES))
        lines = file.read().decode(errors="replace").splitlines()
    return lines[-1] if lines else ""


def last_run(log: Path) -> datetime | None:
    """Return when the snapshot agent last ran without an error, or None.

    The agent writes a snapshot only on a change, but it logs each run. When the last line of the
    log is a run line, the time of the log is the time of that run.
    """
    if not log.exists() or not RUN_LINE_RE.match(last_line(log)):
        return None
    return datetime.fromtimestamp(log.stat().st_mtime)


def newest_snapshot() -> store.Summary | None:
    """Return the newest snapshot, or None. A missing database stays missing."""
    if not settings().database.exists():
        return None
    newest = store.summaries(1)
    return newest[0] if newest else None


def age_text(age: timedelta) -> str:
    """Return an age in minutes, hours or days, whichever is the shortest readable form."""
    minutes = int(age.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min"
    hours = minutes // 60
    return f"{hours} h" if hours < 48 else f"{hours // 24} d"


def snapshot_age_check(now: datetime) -> Check:
    """Tell if the snapshot agent ran in the last 3 intervals. A run without a change counts."""
    newest = newest_snapshot()
    if newest is None:
        return Check(AGE, FAIL, "no snapshot: run `ai-tabs snapshot`")
    seen = max(newest.created_at, last_run(LAUNCHD_LOG) or newest.created_at)
    limit = timedelta(seconds=STALE_RUNS * settings().snapshot_interval)
    status = WARN if now - seen > limit else OK
    return Check(AGE, status, f"newest snapshot {newest.id} ({age_text(now - newest.created_at)} ago), "
                              f"last run {age_text(now - seen)} ago")


def database_answers(path: Path) -> tuple[str, int]:
    """Return the result of `PRAGMA integrity_check` and the number of snapshots, from a read-only connection."""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        count = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    return integrity, count


def database_check() -> Check:
    """Tell if the database passes the SQLite integrity check, and how many snapshots it holds."""
    path = settings().database
    if not path.exists():
        return Check(DATABASE, FAIL, f"{path} does not exist")
    try:
        integrity, count = database_answers(path)
    except sqlite3.DatabaseError as error:
        return Check(DATABASE, FAIL, f"{path}: {error}")
    if integrity != "ok":
        return Check(DATABASE, FAIL, f"integrity check: {integrity}")
    return Check(DATABASE, OK, f"integrity ok, {count} snapshots in {path}")


def backup_check(today: date) -> Check:
    """Tell how many backups there are and if the newest one is at most 2 days old."""
    folder = settings().backup_dir
    backups = sorted(folder.glob(BACKUP_GLOB))
    if not backups:
        return Check(BACKUPS, WARN, f"no backup in {folder}")
    newest = date.fromisoformat(backups[-1].stem.removeprefix("ai-tabs-"))
    age = today - newest
    status = WARN if age > BACKUP_MAX_AGE else OK
    return Check(BACKUPS, status, f"{len(backups)} backups in {folder}, newest {newest} ({age.days} d ago)")


def process_tty(pid: int) -> str:
    """Return the tty of a process, such as `ttys003`, or an empty string when it has none."""
    tty = run(PS, "-o", "tty=", "-p", str(pid)).strip()
    return "" if tty in NO_TTY else tty


def agent_processes_with_tty() -> list[AgentProcess]:
    """Return every omp and claude process that runs on a tty."""
    processes = [AgentProcess(kind, pid, process_tty(pid)) for kind, pid in agent_processes("-A")]
    return [process for process in processes if process.tty]


def agent_detection_check() -> Check:
    """Tell if each omp and claude process on a tty has a session that `find_agent` finds.

    A process without a session is invisible to the snapshot, and restore loses it.
    """
    processes = agent_processes_with_tty()
    found = {tty: find_agent(tty) is not None for tty in {process.tty for process in processes}}
    unseen = [f"{process.kind} {process.pid} on {process.tty}" for process in processes if not found[process.tty]]
    if unseen:
        return Check(DETECTION, WARN, f"no session found for: {', '.join(unseen)}")
    return Check(DETECTION, OK, f"{len(processes)} agent processes on a tty, each with a session")


def watch_agent_check(program: str) -> Check:
    """Check the watcher agent, or report it as off when the `watch` setting is false."""
    if not settings().watch:
        return Check(WATCH_AGENT.name, OK, "off: the watch setting is false")
    return launch_agent_check(WATCH_AGENT, program)


def run_checks(program: str) -> list[Check]:
    """Run every check. `program` is the program that the launchd agents must run."""
    now = datetime.now()
    return [
        *iterm_checks(),
        launch_agent_check(SNAPSHOT_AGENT, program),
        watch_agent_check(program),
        snapshot_age_check(now),
        database_check(),
        backup_check(now.date()),
        agent_detection_check(),
    ]


def has_failure(checks: list[Check]) -> bool:
    """Tell if at least one check failed."""
    return any(check.status == FAIL for check in checks)


def checks_table(checks: list[Check], colors: Palette) -> Table:
    """Return a table with one row per check: the status in its color, the name and the detail."""
    styles = {OK: colors.green, WARN: colors.gold, FAIL: colors.red}
    table = Table("Status", "Check", "Detail")
    for check in checks:
        table.add_row(f"[{styles[check.status]}]{check.status}[/]", check.name, escape(check.detail))
    return table


def print_checks(checks: list[Check], colors: Palette) -> None:
    """Print the table of the checks."""
    console.print(checks_table(checks, colors))

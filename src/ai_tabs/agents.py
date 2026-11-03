"""Find the omp, Claude Code, opencode and hermes sessions that run in a terminal, and how to resume them."""

import json
import os
import re
import shlex
import sqlite3
import time
from contextlib import closing
from functools import cache
from pathlib import Path

from .config import CLAUDE_PID_DIR, HERMES_DB, LSOF, OMP_SESSION_DIR, OPENCODE_DB, PS
from .models import Agent
from .system import run

SWITCH, VALUE, VALUES = "switch", "value", "values"

# Launch settings that a resumed session keeps. Everything else is dropped: session selection,
# one-shot flags, secrets, unknown flags and every positional argument, so that a prompt never runs again.
CLAUDE_FLAGS = {
    "--dangerously-skip-permissions": SWITCH, "--allow-dangerously-skip-permissions": SWITCH,
    "--ide": SWITCH, "--chrome": SWITCH, "--no-chrome": SWITCH, "--verbose": SWITCH,
    "--strict-mcp-config": SWITCH, "--disable-slash-commands": SWITCH, "--brief": SWITCH,
    "--model": VALUE, "--permission-mode": VALUE, "--settings": VALUE, "--agent": VALUE,
    "--agents": VALUE, "--effort": VALUE, "--fallback-model": VALUE, "--plugin-dir": VALUE,
    "--append-system-prompt": VALUE, "--system-prompt": VALUE, "--setting-sources": VALUE,
    "--add-dir": VALUES, "--mcp-config": VALUES, "--allowed-tools": VALUES, "--allowedTools": VALUES,
    "--disallowed-tools": VALUES, "--disallowedTools": VALUES, "--tools": VALUES, "--betas": VALUES,
}
OMP_FLAGS = {
    "--auto-approve": SWITCH, "--advisor": SWITCH, "--no-lsp": SWITCH, "--no-pty": SWITCH,
    "--no-tools": SWITCH, "--no-extensions": SWITCH, "--no-skills": SWITCH, "--no-rules": SWITCH,
    "--no-context-files": SWITCH, "--no-title": SWITCH, "--hide-thinking": SWITCH,
    "--allow-home": SWITCH, "--prewalk": SWITCH, "--no-prewalk": SWITCH, "--plan-yolo": SWITCH,
    "--model": VALUE, "--smol": VALUE, "--slow": VALUE, "--plan": VALUE, "--thinking": VALUE,
    "--profile": VALUE, "--provider": VALUE, "--approval-mode": VALUE, "--add-dir": VALUE,
    "--config": VALUE, "--session-dir": VALUE, "--models": VALUE, "--tools": VALUE,
    "--skills": VALUE, "--extension": VALUE, "-e": VALUE, "--hook": VALUE,
    "--prewalk-into": VALUE, "--plan-yolo-into": VALUE, "--service-tier": VALUE,
    "--system-prompt": VALUE, "--append-system-prompt": VALUE, "--system-prompt-template": VALUE,
    "--max-time": VALUE, "--warn-cost": VALUE, "--max-cost": VALUE,
}
OPENCODE_FLAGS = {
    "--pure": SWITCH, "--print-logs": SWITCH, "--log-level": VALUE, "--model": VALUE, "-m": VALUE, "--agent": VALUE,
}
HERMES_FLAGS = {
    "--yolo": SWITCH, "--accept-hooks": SWITCH, "--checkpoints": SWITCH, "--pass-session-id": SWITCH,
    "--ignore-user-config": SWITCH, "--ignore-rules": SWITCH, "--safe-mode": SWITCH, "--tui": SWITCH,
    "--cli": SWITCH, "--verbose": SWITCH, "-v": SWITCH,
    "--model": VALUE, "-m": VALUE, "--provider": VALUE, "--reasoning": VALUE, "--toolsets": VALUE, "-t": VALUE,
    "--skills": VALUE, "-s": VALUE, "--max-turns": VALUE,
}
# The hermes flags that take a value, so that the value is not read as the subcommand.
HERMES_VALUE_FLAGS = frozenset({
    "-z", "--usage-file", "-m", "--model", "--provider", "--reasoning", "-t", "--toolsets", "-r", "--resume",
    "-c", "--continue", "--skills", "-s", "-q", "--query", "--image", "--max-turns", "--source",
})
HERMES_SCRIPT_SUFFIX = "/hermes-agent/hermes"
NAMED_KINDS = ("omp", "claude", "opencode")
SECRET_FLAGS = ("--api-key", "--password")
REDACTED = "***"


def process_argv(pid: int) -> list[str]:
    """Return the command line of a process as a list of words.

    `ps` prints the words joined by spaces and drops the original quoting, so a word that
    holds a space comes back as two words.
    """
    try:
        return shlex.split(run(PS, "-o", "args=", "-p", str(pid)).strip())
    except ValueError:
        return []


def redact_word(word: str, previous: str) -> str:
    """Return the word, or `***` when it is the value of a secret flag."""
    flag, has_value, _ = word.partition("=")
    if has_value and flag in SECRET_FLAGS:
        return f"{flag}={REDACTED}"
    return REDACTED if previous in SECRET_FLAGS else word


def redact_secrets(argv: list[str]) -> list[str]:
    """Replace the value of every secret flag, in the `--flag=X` and `--flag X` forms."""
    return [redact_word(word, previous) for previous, word in zip(["", *argv], argv, strict=False)]


def flag_values(words: list[str], arity: str) -> list[str]:
    """Return the values at the start of `words` that a flag of this arity takes."""
    if arity == SWITCH:
        return []
    if arity == VALUE:
        return words[:1]
    count = next((index for index, word in enumerate(words) if word.startswith("-")), len(words))
    return words[:count]


def kept_flags(argv: list[str], allowed: dict[str, str]) -> list[tuple[str, list[str]]]:
    """Return the allowed flags of `argv` with their values. `argv[0]` is the program."""
    kept, index = [], 1
    while index < len(argv):
        name, has_value, inline = argv[index].partition("=")
        index += 1
        arity = allowed.get(name) if name.startswith("-") else None
        if arity is None:
            continue
        values = [inline] if has_value else flag_values(argv[index:], arity)
        index += 0 if has_value else len(values)
        kept.append((name, values))
    return kept


def spaced_flags(argv: list[str], allowed: dict[str, str]) -> str:
    """Return the allowed launch flags of a command line to repeat on resume, in `--flag value` form."""
    words = [" ".join([name, *map(shlex.quote, values)]) for name, values in kept_flags(argv, allowed)]
    return " ".join(words)


def claude_flags(argv: list[str]) -> str:
    """Return the launch flags of a claude command line to repeat on resume, in `--flag value` form."""
    return spaced_flags(argv, CLAUDE_FLAGS)


def omp_flags(argv: list[str]) -> str:
    """Return the launch flags of an omp command line to repeat on resume, in `--flag=value` form."""
    words = [name + "".join(f"={shlex.quote(value)}" for value in values)
             for name, values in kept_flags(argv, OMP_FLAGS)]
    return " ".join(words)


def with_flags(command: str, flags: str) -> str:
    """Append the flags to the command, when there are flags."""
    return f"{command} {flags}" if flags else command


def last_flag_value(argv: list[str], names: tuple[str, ...]) -> str:
    """Return the value of the last of these flags in the command line, or an empty string. `argv[0]` is the program."""
    values = [values[0] for _, values in kept_flags(argv, dict.fromkeys(names, VALUE)) if values]
    return values[-1] if values else ""


def first_positional(words: list[str], value_flags: frozenset[str]) -> str:
    """Return the first word that is not a flag or the value of a flag, or an empty string."""
    index = 0
    while index < len(words):
        word = words[index]
        if not word.startswith("-"):
            return word
        index += 2 if word in value_flags else 1
    return ""


def is_hermes_chat(argv: list[str]) -> bool:
    """Tell if the command line runs the hermes chat: the hermes-agent script with no subcommand, or with `chat`."""
    runs_script = len(argv) > 1 and argv[1].endswith(HERMES_SCRIPT_SUFFIX)
    return runs_script and first_positional(argv[2:], HERMES_VALUE_FLAGS) in ("", "chat")


def process_kind(pid: int, command: str) -> str | None:
    """Return the agent kind of a process from its executable, or None when the process is not an agent.

    hermes runs in Python, which a framework build names `Python`. A Python process is a hermes agent only
    when its command line runs the hermes chat, so other Python and node programs never match.
    """
    name = os.path.basename(command)
    if name in NAMED_KINDS:
        return name
    if name.lower().startswith("python") and is_hermes_chat(process_argv(pid)):
        return "hermes"
    return None


def agent_processes(*ps_arguments: str) -> list[tuple[str, int]]:
    """Return the kind and PID of every omp, claude, opencode or hermes process that `ps` lists."""
    output = run(PS, *ps_arguments, "-o", "pid=,comm=")
    found = []
    for line in output.splitlines():
        pid, _, command = line.strip().partition(" ")
        kind = process_kind(int(pid), command.strip())
        if kind:
            found.append((kind, int(pid)))
    return found


def claude_agent(pid: int) -> Agent | None:
    """Read the session of a Claude Code process from its PID file."""
    pid_file = CLAUDE_PID_DIR / f"{pid}.json"
    if not pid_file.exists():
        return None
    info = json.loads(pid_file.read_text())
    session_id = info.get("sessionId", "")
    cwd = info.get("cwd", "")
    argv = process_argv(pid)
    resume = with_flags(f"cd {shlex.quote(cwd)} && claude --resume {session_id}", claude_flags(argv))
    return Agent("claude", pid, cwd, session_id, info.get("name", ""), resume, argv)


OMP_SESSION_RE = re.compile(re.escape(str(OMP_SESSION_DIR)) + r"/[^/]+/[^/]+\.jsonl$")


def omp_open_session_file(pid: int) -> Path | None:
    """Return the main session file that the omp process holds open."""
    for line in run(LSOF, "-p", str(pid), "-Fn").splitlines():
        path = line[1:]
        if line.startswith("n") and OMP_SESSION_RE.match(path):
            return Path(path)
    return None


def omp_resumed_session_file(argv: list[str]) -> Path | None:
    """Return the session file of the `--resume` or `-r` flag, when the flag names an existing session file."""
    values = [values for name, values in kept_flags(argv, {"--resume": VALUE, "-r": VALUE}) if values]
    path = values[-1][0] if values else ""
    return Path(path) if OMP_SESSION_RE.match(path) and Path(path).is_file() else None


def omp_session_file(pid: int, argv: list[str]) -> Path | None:
    """Return the session file of the omp process: the file that it holds open, else the file of `--resume`.

    omp holds the session file open only while it writes to it. A resumed session without a new
    message has no open file.
    """
    return omp_open_session_file(pid) or omp_resumed_session_file(argv)


def omp_agent(pid: int) -> Agent | None:
    """Read the session of an omp process from its session file."""
    argv = redact_secrets(process_argv(pid))
    session_file = omp_session_file(pid, argv)
    if session_file is None:
        return None
    with session_file.open() as handle:
        records = [json.loads(handle.readline()) for _ in range(2)]
    headers = {record.get("type"): record for record in records}
    session = headers.get("session", {})
    cwd = session.get("cwd", "")
    title = headers.get("title", {}).get("title", "")
    resume = with_flags(f"cd {shlex.quote(cwd)} && omp --resume {shlex.quote(str(session_file))}", omp_flags(argv))
    return Agent("omp", pid, cwd, session.get("id", ""), title, resume, argv)


ELAPSED_RE = re.compile(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)$")


def process_start(pid: int) -> float | None:
    """Return a time, in seconds since the epoch, at most one second before the process started.

    `ps` prints the elapsed time `[[dd-]hh:]mm:ss` in whole seconds and without the locale of `lstart`.
    """
    match = ELAPSED_RE.match(run(PS, "-o", "etime=", "-p", str(pid)).strip())
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return time.time() - (((days * 24 + hours) * 60 + minutes) * 60 + seconds) - 1


def process_cwd(pid: int) -> str:
    """Return the working folder of a process, or an empty string when `lsof` gives no answer."""
    lines = run(LSOF, "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines()
    return next((line[1:] for line in lines if line.startswith("n")), "")


def read_rows(database: Path, query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    """Return the rows of a query on a database opened read only.

    opencode and hermes write to their databases while they run. A missing, locked or changed database
    gives no rows.
    """
    if not database.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(query, parameters).fetchall()
    except sqlite3.Error:
        return []


def row_in_folder(rows: list[sqlite3.Row], cwd: str) -> sqlite3.Row | None:
    """Return the first row whose `cwd` column is the folder `cwd`."""
    folder = os.path.realpath(cwd) if cwd else ""
    return next((row for row in rows if row["cwd"] and os.path.realpath(row["cwd"]) == folder), None)


OPENCODE_BY_ID = "SELECT id, directory AS cwd, title FROM session WHERE id = ?"
OPENCODE_STARTED_AFTER = ("SELECT id, directory AS cwd, title FROM session WHERE parent_id IS NULL "
                          "AND time_created >= ? ORDER BY time_updated DESC")


def opencode_session(pid: int, argv: list[str]) -> sqlite3.Row | None:
    """Return the session row of an opencode process.

    The row is the session of `--session` or `-s`. Without the flag, it is the most recently changed top-level
    session that started in the process folder after the process started: the command line does not show it.
    """
    chosen = last_flag_value(argv, ("--session", "-s"))
    if chosen:
        return next(iter(read_rows(OPENCODE_DB, OPENCODE_BY_ID, (chosen,))), None)
    start = process_start(pid)
    rows = read_rows(OPENCODE_DB, OPENCODE_STARTED_AFTER, (start * 1000,)) if start else []
    return row_in_folder(rows, process_cwd(pid))


def opencode_resume(cwd: str, session_id: str) -> str:
    """Return the command that resumes an opencode session."""
    return f"cd {shlex.quote(cwd)} && opencode --session {shlex.quote(session_id)}"


def opencode_agent(pid: int) -> Agent | None:
    """Read the session of an opencode process from the opencode database."""
    argv = redact_secrets(process_argv(pid))
    row = opencode_session(pid, argv)
    if row is None:
        return None
    resume = with_flags(opencode_resume(row["cwd"], row["id"]), spaced_flags(argv, OPENCODE_FLAGS))
    return Agent("opencode", pid, row["cwd"], row["id"], row["title"] or "", resume, argv)


HERMES_BY_ID = "SELECT id, cwd, title FROM sessions WHERE id = ?"
HERMES_STARTED_AFTER = ("SELECT id, cwd, title FROM sessions WHERE source IN ('cli', 'tui') AND ended_at IS NULL "
                        "AND started_at >= ? ORDER BY started_at DESC")


def hermes_session(pid: int, argv: list[str]) -> sqlite3.Row | None:
    """Return the session row of a hermes process. `argv[0]` is Python and `argv[1]` is the hermes script.

    The row is the session of `--resume` or `-r`. Without the flag, it is the newest open chat session that
    started in the process folder after the process started. hermes writes the row at the first message.
    """
    chosen = last_flag_value(argv[1:], ("--resume", "-r"))
    if chosen:
        return next(iter(read_rows(HERMES_DB, HERMES_BY_ID, (chosen,))), None)
    start = process_start(pid)
    rows = read_rows(HERMES_DB, HERMES_STARTED_AFTER, (start,)) if start else []
    return row_in_folder(rows, process_cwd(pid))


def hermes_resume(cwd: str, session_id: str) -> str:
    """Return the command that resumes a hermes session in the chat."""
    return f"cd {shlex.quote(cwd)} && hermes chat --resume {shlex.quote(session_id)}"


def hermes_agent(pid: int) -> Agent | None:
    """Read the session of a hermes process from the hermes state database."""
    argv = redact_secrets(process_argv(pid))
    row = hermes_session(pid, argv)
    if row is None:
        return None
    cwd = row["cwd"] or process_cwd(pid)
    resume = with_flags(hermes_resume(cwd, row["id"]), spaced_flags(argv[1:], HERMES_FLAGS))
    return Agent("hermes", pid, cwd, row["id"], row["title"] or "", resume, argv)


AGENT_READERS = {"claude": claude_agent, "omp": omp_agent, "opencode": opencode_agent, "hermes": hermes_agent}


def find_agent(tty: str) -> Agent | None:
    """Return the agent that runs on the tty, if there is one.

    A tty can also hold omp helper processes, such as `__omp_worker_stt`. They
    have no session, so the first process with a session wins.
    """
    agents = (AGENT_READERS[kind](pid) for kind, pid in agent_processes("-t", tty.removeprefix("/dev/")))
    return next((agent for agent in agents if agent), None)


@cache
def running_sessions() -> frozenset[tuple[str, str]]:
    """Return the kind and session ID of every agent session that runs now."""
    agents = (AGENT_READERS[kind](pid) for kind, pid in agent_processes("-A"))
    return frozenset((agent.kind, agent.session_id) for agent in agents if agent)


def is_still_running(agent: Agent) -> bool:
    """Tell if the agent session runs now, in any process.

    The saved PID is not enough: a session resumed after a restart runs under a new PID.
    """
    return (agent.kind, agent.session_id) in running_sessions()

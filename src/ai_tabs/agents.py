"""Find the omp and Claude Code sessions that run in a terminal, and how to resume them."""

import json
import os
import re
import shlex
from functools import cache
from pathlib import Path

from .config import CLAUDE_PID_DIR, LSOF, OMP_SESSION_DIR, PS
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
SECRET_FLAGS = ("--api-key",)
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


def claude_flags(argv: list[str]) -> str:
    """Return the launch flags of a claude command line to repeat on resume, in `--flag value` form."""
    words = [" ".join([name, *map(shlex.quote, values)]) for name, values in kept_flags(argv, CLAUDE_FLAGS)]
    return " ".join(words)


def omp_flags(argv: list[str]) -> str:
    """Return the launch flags of an omp command line to repeat on resume, in `--flag=value` form."""
    words = [name + "".join(f"={shlex.quote(value)}" for value in values)
             for name, values in kept_flags(argv, OMP_FLAGS)]
    return " ".join(words)


def with_flags(command: str, flags: str) -> str:
    """Append the flags to the command, when there are flags."""
    return f"{command} {flags}" if flags else command


def agent_processes(*ps_arguments: str) -> list[tuple[str, int]]:
    """Return the kind and PID of every omp or claude process that `ps` lists."""
    output = run(PS, *ps_arguments, "-o", "pid=,comm=")
    found = []
    for line in output.splitlines():
        pid, _, command = line.strip().partition(" ")
        kind = os.path.basename(command.strip())
        if kind in ("omp", "claude"):
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


def omp_session_file(pid: int) -> Path | None:
    """Return the main session file that the omp process holds open."""
    session_re = re.compile(re.escape(str(OMP_SESSION_DIR)) + r"/[^/]+/[^/]+\.jsonl$")
    for line in run(LSOF, "-p", str(pid), "-Fn").splitlines():
        path = line[1:]
        if line.startswith("n") and session_re.match(path):
            return Path(path)
    return None


def omp_agent(pid: int) -> Agent | None:
    """Read the session of an omp process from its open session file."""
    session_file = omp_session_file(pid)
    if session_file is None:
        return None
    with session_file.open() as handle:
        records = [json.loads(handle.readline()) for _ in range(2)]
    headers = {record.get("type"): record for record in records}
    session = headers.get("session", {})
    cwd = session.get("cwd", "")
    title = headers.get("title", {}).get("title", "")
    argv = redact_secrets(process_argv(pid))
    resume = with_flags(f"cd {shlex.quote(cwd)} && omp --resume {shlex.quote(str(session_file))}", omp_flags(argv))
    return Agent("omp", pid, cwd, session.get("id", ""), title, resume, argv)


AGENT_READERS = {"claude": claude_agent, "omp": omp_agent}


def find_agent(tty: str) -> Agent | None:
    """Return the agent that runs on the tty, if there is one.

    A tty can also hold omp helper processes, such as `__omp_worker_stt`. They
    have no session, so the first process with a session wins.
    """
    agents = (AGENT_READERS[kind](pid) for kind, pid in agent_processes("-t", tty.removeprefix("/dev/")))
    return next((agent for agent in agents if agent), None)


@cache
def running_sessions() -> frozenset[tuple[str, str]]:
    """Return the kind and session ID of every omp and Claude Code session that runs now."""
    agents = (AGENT_READERS[kind](pid) for kind, pid in agent_processes("-A"))
    return frozenset((agent.kind, agent.session_id) for agent in agents if agent)


def is_still_running(agent: Agent) -> bool:
    """Tell if the agent session runs now, in any process.

    The saved PID is not enough: a session resumed after a restart runs under a new PID.
    """
    return (agent.kind, agent.session_id) in running_sessions()

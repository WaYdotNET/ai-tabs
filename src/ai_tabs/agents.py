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
    resume = f"cd {shlex.quote(cwd)} && claude --resume {session_id}"
    return Agent("claude", pid, cwd, session_id, info.get("name", ""), resume)


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
    resume = f"cd {shlex.quote(cwd)} && omp --resume {shlex.quote(str(session_file))}"
    return Agent("omp", pid, cwd, session.get("id", ""), title, resume)


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

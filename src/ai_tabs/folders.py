"""Find the working folder of the program that runs in the foreground of a tty.

iTerm2 updates the `path` variable of a session only when the shell shows a prompt. A pane
that runs `cd X && program` keeps the folder of the previous prompt, so the folder of the
foreground process is the better value.
"""

import os
from typing import NamedTuple

from .config import LSOF, PS
from .system import run

SHELLS = frozenset({"zsh", "bash", "fish", "sh"})


class TtyProcess(NamedTuple):
    """One process on a tty, as `ps` lists it."""

    pid: int
    tpgid: int
    pgid: int
    command: str


def parse_process(line: str) -> TtyProcess | None:
    """Parse one `ps -o pid=,tpgid=,pgid=,comm=` line, or return None if the line is not valid."""
    fields = line.split(maxsplit=3)
    if len(fields) != 4 or not all(field.lstrip("-").isdigit() for field in fields[:3]):
        return None
    pid, tpgid, pgid = (int(field) for field in fields[:3])
    return TtyProcess(pid, tpgid, pgid, fields[3])


def tty_processes(tty: str) -> list[TtyProcess]:
    """Return the processes that run on the tty."""
    output = run(PS, "-o", "pid=,tpgid=,pgid=,comm=", "-t", tty.removeprefix("/dev/"))
    parsed = (parse_process(line) for line in output.splitlines())
    return [process for process in parsed if process]


def foreground_process(processes: list[TtyProcess]) -> TtyProcess | None:
    """Return the leader of the foreground process group, else the newest process (highest PID).

    The foreground group is the group whose ID is the tpgid of the tty.
    """
    foreground = [process for process in processes if process.pgid == process.tpgid]
    leaders = [process for process in foreground if process.pid == process.pgid]
    candidates = leaders or foreground or processes
    return max(candidates, key=lambda process: process.pid) if candidates else None


def is_shell(process: TtyProcess) -> bool:
    """Tell if the process is a shell. A login shell has a `-` before its name."""
    name = os.path.basename(process.command.strip()).removeprefix("-")
    return name in SHELLS


def process_cwd(pid: int) -> str:
    """Return the working folder of the process, or an empty string if `lsof` gives no answer."""
    lines = run(LSOF, "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines()
    return next((line[1:] for line in lines if line.startswith("n")), "")


def pane_folder(tty: str, iterm_path: str) -> str:
    """Return the working folder of the foreground program on the tty, else the iTerm2 path.

    At a prompt the foreground process is the shell, and the iTerm2 path is correct.
    """
    process = foreground_process(tty_processes(tty)) if tty else None
    if process is None or is_shell(process):
        return iterm_path
    return process_cwd(process.pid) or iterm_path

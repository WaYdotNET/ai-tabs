"""Find the recent omp and Claude Code sessions that do not run now, and build a window that resumes them."""

import json
import shlex
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from rich.table import Column, Table

from . import agents
from .config import HOME, OMP_SESSION_DIR
from .display import console, short_path
from .models import Agent, Pane, Tab, Window

CLAUDE_PROJECTS_DIR = HOME / ".claude/projects"

# Session files can be many MB: only the first lines and the last bytes are read.
HEAD_LINES = 200
LINE_LIMIT = 1 << 20
TAIL_BYTES = 256 * 1024
TITLE_LENGTH = 60
SHORT_ID_LENGTH = 8
SECONDS_PER_DAY = 86400
NEW_WINDOW_FRAME = [100.0, 100.0, 1200.0, 800.0]
# ID, kind and time columns, plus the table borders and padding.
FIXED_COLUMNS_WIDTH = SHORT_ID_LENGTH + 6 + 11 + 16
MIN_TEXT_WIDTH = 12

# Claude Code title records, from the strongest to the weakest. The last record of a type wins.
CLAUDE_TITLE_FIELDS = (("custom-title", "customTitle"), ("agent-name", "agentName"), ("ai-title", "aiTitle"))
SDK_ENTRYPOINT_PREFIX = "sdk-"


@dataclass(frozen=True)
class Session:
    """A saved omp or Claude Code session. `modified` is the time of its last activity."""

    kind: str
    session_id: str
    cwd: str
    title: str
    path: Path
    modified: datetime


def parse_record(line: bytes) -> dict:
    """Return the JSON object of one line, or an empty dict when the line is not a complete JSON object."""
    try:
        record = json.loads(line)
    except ValueError:
        return {}
    return record if isinstance(record, dict) else {}


def head_records(path: Path, count: int) -> list[dict]:
    """Return the JSON objects of the first `count` lines of a file."""
    lines = []
    with path.open("rb") as handle:
        for _ in range(count):
            lines.append(handle.readline(LINE_LIMIT))
    return [record for record in map(parse_record, lines) if record]


def tail_records(path: Path) -> list[dict]:
    """Return the JSON objects of the complete lines in the last TAIL_BYTES of a file."""
    start = max(0, path.stat().st_size - TAIL_BYTES)
    with path.open("rb") as handle:
        handle.seek(start)
        lines = handle.read().splitlines()
    complete = lines[1:] if start else lines
    return [record for record in map(parse_record, complete) if record]


def modified_time(path: Path) -> datetime:
    """Return the time of the last change of a file."""
    return datetime.fromtimestamp(path.stat().st_mtime)


def omp_session(path: Path) -> Session | None:
    """Read an omp session from the `session` and `title` headers of its file."""
    headers = {record.get("type"): record for record in head_records(path, 2)}
    session = headers.get("session")
    if session is None:
        return None
    title = headers.get("title", {}).get("title") or session.get("title", "")
    return Session("omp", session.get("id", ""), session.get("cwd", ""), title, path, modified_time(path))


def user_text(record: dict) -> str:
    """Return the text of a user message record: the string content, else the first text block."""
    content = record.get("message", {}).get("content")
    if isinstance(content, list):
        blocks = [block for block in content if isinstance(block, dict) and block.get("type") == "text"]
        content = blocks[0].get("text") if blocks else ""
    return content if isinstance(content, str) else ""


def first_prompt(records: list[dict]) -> str:
    """Return the first message that the user typed, on one line and cut to TITLE_LENGTH characters.

    Text that starts with `<` is a command, a hook output or a pasted block, not a typed prompt.
    """
    prompts = (user_text(record) for record in records if record.get("type") == "user" and not record.get("isMeta"))
    typed = next((text for text in prompts if text.strip() and not text.lstrip().startswith("<")), "")
    return " ".join(typed.split())[:TITLE_LENGTH]


def claude_title(records: list[dict]) -> str:
    """Return the title of a Claude Code session: its strongest title record, else its first prompt."""
    for kind, key in CLAUDE_TITLE_FIELDS:
        titles = [record.get(key) for record in records if record.get("type") == kind and record.get(key)]
        if titles:
            return titles[-1]
    return first_prompt(records)


def is_interactive(head: list[dict]) -> bool:
    """Tell if a Claude Code session started in an interactive client, not with `claude -p` or an SDK.

    The `entrypoint` field of the messages is `sdk-cli`, `sdk-py` or `sdk-ts` for non-interactive runs.
    A file without the field counts as interactive.
    """
    entrypoint = next((record["entrypoint"] for record in head if record.get("entrypoint")), "")
    return not entrypoint.startswith(SDK_ENTRYPOINT_PREFIX)


def claude_session(path: Path) -> Session | None:
    """Read an interactive Claude Code session from its file. The file name is the session ID."""
    head = head_records(path, HEAD_LINES)
    cwd = next((record["cwd"] for record in head if record.get("cwd")), "")
    if not cwd or not is_interactive(head):
        return None
    title = claude_title(head + tail_records(path))
    return Session("claude", path.stem, cwd, title, path, modified_time(path))


def is_omp_session_file(path: Path) -> bool:
    """Tell if the path is a main omp session file, not a helper file such as `__advisor.jsonl` or a lock."""
    return path.is_file() and not path.name.startswith(("_", "."))


def session_files(cutoff: float) -> list[tuple[str, Path]]:
    """Return the kind and path of every session file that changed after the cutoff time."""
    omp = [("omp", path) for path in OMP_SESSION_DIR.glob("*/*.jsonl") if is_omp_session_file(path)]
    claude = [("claude", path) for path in CLAUDE_PROJECTS_DIR.glob("*/*.jsonl") if path.is_file()]
    return [(kind, path) for kind, path in omp + claude if path.stat().st_mtime >= cutoff]


SESSION_READERS = {"omp": omp_session, "claude": claude_session}


def recent_sessions(days: int) -> list[Session]:
    """Return the sessions active in the last `days` days that do not run now, newest first."""
    cutoff = time.time() - days * SECONDS_PER_DAY
    found = [SESSION_READERS[kind](path) for kind, path in session_files(cutoff)]
    running = agents.running_sessions()
    stopped = [session for session in found if session and (session.kind, session.session_id) not in running]
    return sorted(stopped, key=lambda session: session.modified, reverse=True)


def matching_sessions(listed: list[Session], prefix: str) -> list[Session]:
    """Return the listed sessions whose ID starts with the prefix."""
    return [session for session in listed if session.session_id.startswith(prefix)]


def text_column_width(total: int) -> int:
    """Return the width of the folder column and of the title column, for a table `total` characters wide."""
    return max((total - FIXED_COLUMNS_WIDTH) // 2, MIN_TEXT_WIDTH)


def print_recent_sessions(listed: list[Session]) -> None:
    """Print the sessions as a table: short ID, kind, last activity, folder and title."""
    text_width = text_column_width(console.width)
    table = Table("ID", "Kind", "Last used",
                  Column("Folder", width=text_width, no_wrap=True, overflow="ellipsis"),
                  Column("Title", width=text_width, no_wrap=True, overflow="ellipsis"))
    for session in listed:
        table.add_row(session.session_id[:SHORT_ID_LENGTH], session.kind, f"{session.modified:%m-%d %H:%M}",
                      escape(short_path(session.cwd)), escape(session.title))
    console.print(table)


def omp_resume(session: Session) -> str:
    """Return the command that resumes an omp session from its file."""
    return f"cd {shlex.quote(session.cwd)} && omp --resume {shlex.quote(str(session.path))}"


def claude_resume(session: Session) -> str:
    """Return the command that resumes a Claude Code session from its ID."""
    return f"cd {shlex.quote(session.cwd)} && claude --resume {shlex.quote(session.session_id)}"


RESUME_COMMANDS = {"omp": omp_resume, "claude": claude_resume}


def session_tab(session: Session) -> Tab:
    """Return a tab with one pane that resumes the session. The tab has the session title."""
    resume = RESUME_COMMANDS[session.kind](session)
    agent = Agent(session.kind, 0, session.cwd, session.session_id, session.title, resume)
    title = session.title or session.session_id[:SHORT_ID_LENGTH]
    return Tab(title, None, [Pane(session.kind, "", session.cwd, agent)])


def sessions_window(chosen: list[Session]) -> Window:
    """Return one window with one tab for each session."""
    return Window(list(NEW_WINDOW_FRAME), [session_tab(session) for session in chosen])

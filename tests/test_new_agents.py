"""Detection, session reading, resume commands and launch flags of the opencode and hermes agents."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_tabs import agents, sessions
from ai_tabs.config import LSOF, PS

NOW = 1_800_000_000.0
HERMES_SCRIPT = "/Users/me/.hermes/hermes-agent/hermes"
HERMES_PYTHON = "/Users/me/.hermes/hermes-agent/venv/bin/python"
OPENCODE_SCHEMA = ("CREATE TABLE session (id TEXT, parent_id TEXT, directory TEXT, title TEXT, "
                   "time_created INTEGER, time_updated INTEGER, time_archived INTEGER)")
HERMES_SCHEMA = ("CREATE TABLE sessions (id TEXT, source TEXT, cwd TEXT, title TEXT, started_at REAL, ended_at REAL, "
                 "end_reason TEXT, last_activity_at REAL, archived INTEGER DEFAULT 0)")


def write_rows(database: Path, schema: str, rows: list[dict]) -> Path:
    """Create a database with one table from the schema, and insert the rows."""
    table = schema.split()[2]
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(schema)
        for row in rows:
            columns = ", ".join(row)
            marks = ", ".join("?" * len(row))
            connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))
        connection.commit()
    return database


@pytest.fixture
def opencode_db(tmp_path):
    """Return a function that writes the opencode sessions to the isolated opencode database."""
    return lambda *rows: write_rows(tmp_path / "opencode.db", OPENCODE_SCHEMA, list(rows))


@pytest.fixture
def hermes_db(tmp_path):
    """Return a function that writes the hermes sessions to the isolated hermes database."""
    return lambda *rows: write_rows(tmp_path / "hermes.db", HERMES_SCHEMA, list(rows))


@pytest.fixture
def system(monkeypatch):
    """Replace `run` with a fake that answers known commands, and stop the clock of agents at NOW."""
    outputs = {}
    monkeypatch.setattr(agents, "run", lambda *command: outputs.get(command, ""))
    monkeypatch.setattr(agents, "time", SimpleNamespace(time=lambda: NOW))
    return outputs


def add_process(outputs: dict, pid: int, args: str, cwd: str = "/work/app", elapsed: str = "10:00") -> None:
    """Make the fake system show a process with its command line, working folder and elapsed time."""
    outputs[(PS, "-o", "args=", "-p", str(pid))] = args + "\n"
    outputs[(PS, "-o", "etime=", "-p", str(pid))] = f"   {elapsed}\n"
    outputs[(LSOF, "-a", "-p", str(pid), "-d", "cwd", "-Fn")] = f"p{pid}\nfcwd\nn{cwd}\n"


def list_tty(outputs: dict, text: str) -> None:
    """Make the fake `ps` list these PID and executable lines on ttys001."""
    outputs[(PS, "-t", "ttys001", "-o", "pid=,comm=")] = text


@pytest.fixture
def no_session_files(tmp_path, monkeypatch):
    """Point the omp and Claude Code session folders at empty folders."""
    monkeypatch.setattr(sessions, "OMP_SESSION_DIR", tmp_path / "omp")
    monkeypatch.setattr(sessions, "CLAUDE_PROJECTS_DIR", tmp_path / "claude")


# Process detection


def test_opencode_process_is_found_by_its_executable_name(system):
    list_tty(system, "  42 /Users/me/.opencode/bin/opencode\n")

    found = agents.agent_processes("-t", "ttys001")

    assert found == [("opencode", 42)]


def test_node_process_of_the_hermes_folder_is_not_an_agent(system):
    list_tty(system, "  43 node\n")
    add_process(system, 43, "/Users/me/.hermes/node/bin/node /Users/me/plugin/scripts/mcp-server.cjs")

    found = agents.agent_processes("-t", "ttys001")

    assert found == []


def test_python_process_that_runs_the_hermes_script_is_hermes(system):
    list_tty(system, "  44 python3.11\n")
    add_process(system, 44, f"{HERMES_PYTHON} {HERMES_SCRIPT} --yolo")

    found = agents.agent_processes("-t", "ttys001")

    assert found == [("hermes", 44)]


def test_framework_python_process_that_runs_the_hermes_script_is_hermes(system):
    list_tty(system, "  48 /opt/homebrew/Frameworks/Python.framework/Resources/Python.app/Contents/MacOS/Python\n")
    add_process(system, 48, f"Python {HERMES_SCRIPT} chat")

    found = agents.agent_processes("-t", "ttys001")

    assert found == [("hermes", 48)]


def test_python_process_of_the_hermes_chat_subcommand_is_hermes(system):
    list_tty(system, "  44 python3.11\n")
    add_process(system, 44, f"{HERMES_PYTHON} {HERMES_SCRIPT} --model gateway chat -s review")

    found = agents.agent_processes("-t", "ttys001")

    assert found == [("hermes", 44)]


def test_python_process_of_another_hermes_subcommand_is_not_an_agent(system):
    list_tty(system, "  45 python3.11\n")
    add_process(system, 45, f"{HERMES_PYTHON} {HERMES_SCRIPT} gateway run")

    found = agents.agent_processes("-t", "ttys001")

    assert found == []


def test_other_python_program_is_not_an_agent(system):
    list_tty(system, "  46 python3.12\n")
    add_process(system, 46, "/usr/bin/python3 /work/app/manage.py runserver")

    found = agents.agent_processes("-t", "ttys001")

    assert found == []


def test_process_start_reads_days_hours_minutes_and_seconds(system):
    add_process(system, 47, "opencode", elapsed="1-02:03:04")

    start = agents.process_start(47)

    assert start == 1_799_906_215.0


# opencode sessions of running processes


def test_opencode_session_flag_names_the_session_and_resume_keeps_allowed_flags(system, opencode_db):
    opencode_db({"id": "ses_abc", "directory": "/work/app", "title": "Fix login",
                 "time_created": 1_700_000_000_000, "time_updated": 1_700_000_000_000})
    add_process(system, 50, "opencode --session ses_abc -m anthropic/opus --prompt hello")

    agent = agents.opencode_agent(50)

    assert (agent.kind, agent.session_id, agent.cwd, agent.title) == ("opencode", "ses_abc", "/work/app", "Fix login")
    assert agent.resume == "cd /work/app && opencode --session ses_abc -m anthropic/opus"


def test_opencode_without_flag_takes_newest_session_of_its_folder_started_after_the_process(system, opencode_db):
    opencode_db(
        {"id": "ses_before", "directory": "/work/app", "title": "", "time_created": 1_799_999_000_000,
         "time_updated": 1_799_999_990_000},
        {"id": "ses_other", "directory": "/work/other", "title": "", "time_created": 1_799_999_700_000,
         "time_updated": 1_799_999_980_000},
        {"id": "ses_child", "parent_id": "ses_new", "directory": "/work/app", "title": "", "time_created":
         1_799_999_800_000, "time_updated": 1_799_999_970_000},
        {"id": "ses_new", "directory": "/work/app", "title": "New work", "time_created": 1_799_999_600_000,
         "time_updated": 1_799_999_960_000},
    )
    add_process(system, 51, "opencode", cwd="/work/app", elapsed="10:00")

    agent = agents.opencode_agent(51)

    assert agent.session_id == "ses_new"


def test_opencode_without_a_session_after_the_process_start_has_no_agent(system, opencode_db):
    opencode_db({"id": "ses_old", "directory": "/work/app", "title": "", "time_created": 1_799_999_000_000,
                 "time_updated": 1_799_999_990_000})
    add_process(system, 52, "opencode", cwd="/work/app", elapsed="10:00")

    agent = agents.opencode_agent(52)

    assert agent is None


def test_opencode_without_database_has_no_agent(system):
    add_process(system, 53, "opencode --session ses_abc")

    agent = agents.opencode_agent(53)

    assert agent is None


# hermes sessions of running processes


def test_hermes_resume_flag_names_the_session_and_resume_keeps_allowed_flags(system, hermes_db):
    hermes_db({"id": "20260805_093519_c4d5c8", "source": "cli", "cwd": "/work/app", "title": "Review",
               "started_at": 1_700_000_000.0})
    add_process(system, 60, f"{HERMES_PYTHON} {HERMES_SCRIPT} chat --resume 20260805_093519_c4d5c8 --yolo -q hello")

    agent = agents.hermes_agent(60)

    assert (agent.kind, agent.session_id, agent.cwd, agent.title) == (
        "hermes", "20260805_093519_c4d5c8", "/work/app", "Review")
    assert agent.resume == "cd /work/app && hermes chat --resume 20260805_093519_c4d5c8 --yolo"


def test_hermes_without_flag_takes_newest_open_chat_session_of_its_folder(system, hermes_db):
    hermes_db(
        {"id": "s_ended", "source": "cli", "cwd": "/work/app", "started_at": 1_799_999_900.0,
         "ended_at": 1_799_999_950.0, "end_reason": "new_session"},
        {"id": "s_subagent", "source": "subagent", "cwd": "/work/app", "started_at": 1_799_999_980.0},
        {"id": "s_open", "source": "cli", "cwd": "/work/app", "title": "Deploy", "started_at": 1_799_999_960.0},
    )
    add_process(system, 61, f"{HERMES_PYTHON} {HERMES_SCRIPT}", cwd="/work/app", elapsed="10:00")

    agent = agents.hermes_agent(61)

    assert (agent.session_id, agent.title) == ("s_open", "Deploy")
    assert agent.resume == "cd /work/app && hermes chat --resume s_open"


def test_find_agent_returns_the_hermes_session_on_the_tty(system, hermes_db):
    hermes_db({"id": "s_open", "source": "cli", "cwd": "/work/app", "started_at": 1_799_999_960.0})
    list_tty(system, "  70 node\n  71 python3.11\n")
    add_process(system, 70, "/Users/me/.hermes/node/bin/node /Users/me/plugin/scripts/mcp-server.cjs")
    add_process(system, 71, f"{HERMES_PYTHON} {HERMES_SCRIPT}", cwd="/work/app", elapsed="10:00")

    agent = agents.find_agent("/dev/ttys001")

    assert (agent.kind, agent.pid, agent.session_id) == ("hermes", 71, "s_open")


# Launch flags


def test_opencode_flags_keep_model_and_agent_and_drop_session_prompt_and_port():
    argv = ["opencode", "-c", "--model", "x/y", "--agent", "plan", "--prompt", "hi", "--port", "4096", "/dir"]

    flags = agents.spaced_flags(argv, agents.OPENCODE_FLAGS)

    assert flags == "--model x/y --agent plan"


def test_hermes_flags_keep_launch_settings_and_drop_resume_query_and_worktree():
    argv = ["hermes", "chat", "-r", "s_1", "--yolo", "-t", "web,terminal", "-q", "hi", "--worktree", "--reasoning=high"]

    flags = agents.spaced_flags(argv, agents.HERMES_FLAGS)

    assert flags == "--yolo -t web,terminal --reasoning high"


def test_redact_secrets_hides_password():
    argv = ["opencode", "run", "--password", "secret", "--model", "x/y"]

    redacted = agents.redact_secrets(argv)

    assert redacted == ["opencode", "run", "--password", "***", "--model", "x/y"]


# Databases


def test_read_rows_of_a_missing_database_is_empty(tmp_path):
    rows = agents.read_rows(tmp_path / "missing.db", "SELECT id FROM session")

    assert rows == []


def test_read_rows_of_a_database_without_the_table_is_empty(tmp_path):
    database = write_rows(tmp_path / "other.db", "CREATE TABLE other (id TEXT)", [])

    rows = agents.read_rows(database, "SELECT id FROM session")

    assert rows == []


def test_read_rows_does_not_change_the_database(tmp_path):
    database = write_rows(tmp_path / "ro.db", "CREATE TABLE session (id TEXT)", [])

    rows = agents.read_rows(database, "INSERT INTO session (id) VALUES ('x') RETURNING id")

    assert rows == []


# Stopped sessions


def test_recent_sessions_list_top_level_opencode_sessions_with_their_resume_command(opencode_db, no_session_files):
    recent = int((time.time() - 3600) * 1000)
    opencode_db(
        {"id": "ses_top", "directory": "/work/app", "title": "Fix login", "time_created": recent,
         "time_updated": recent},
        {"id": "ses_child", "parent_id": "ses_top", "directory": "/work/app", "title": "", "time_created": recent,
         "time_updated": recent},
        {"id": "ses_archived", "directory": "/work/app", "title": "", "time_created": recent, "time_updated": recent,
         "time_archived": recent},
    )

    found = sessions.recent_sessions(7)

    assert [(session.kind, session.session_id, session.title) for session in found] == [
        ("opencode", "ses_top", "Fix login")]
    assert sessions.session_tab(found[0]).panes[0].agent.resume == "cd /work/app && opencode --session ses_top"


def test_recent_sessions_leave_out_old_opencode_sessions(opencode_db, no_session_files):
    old = int((time.time() - 10 * 86400) * 1000)
    opencode_db({"id": "ses_old", "directory": "/work/app", "title": "", "time_created": old, "time_updated": old})

    found = sessions.recent_sessions(7)

    assert found == []


def test_recent_sessions_list_hermes_chat_sessions_with_their_resume_command(hermes_db, no_session_files):
    recent = time.time() - 3600
    hermes_db(
        {"id": "s_chat", "source": "cli", "cwd": "/work/app", "title": "Review", "started_at": recent},
        {"id": "s_subagent", "source": "subagent", "cwd": "/work/app", "started_at": recent},
        {"id": "s_no_folder", "source": "cli", "cwd": None, "started_at": recent},
        {"id": "s_compressed", "source": "cli", "cwd": "/work/app", "started_at": recent, "end_reason": "compression"},
        {"id": "s_archived", "source": "cli", "cwd": "/work/app", "started_at": recent, "archived": 1},
    )

    found = sessions.recent_sessions(7)

    assert [(session.kind, session.session_id, session.title) for session in found] == [("hermes", "s_chat", "Review")]
    assert sessions.session_tab(found[0]).panes[0].agent.resume == "cd /work/app && hermes chat --resume s_chat"


def test_recent_sessions_leave_out_a_running_hermes_session(hermes_db, no_session_files, monkeypatch):
    recent = time.time() - 3600
    hermes_db({"id": "s_running", "source": "cli", "cwd": "/work/app", "started_at": recent},
              {"id": "s_stopped", "source": "cli", "cwd": "/work/app", "started_at": recent})
    monkeypatch.setattr(agents, "running_sessions", lambda: frozenset({("hermes", "s_running")}))

    found = sessions.recent_sessions(7)

    assert [session.session_id for session in found] == ["s_stopped"]


def test_recent_sessions_put_the_newest_session_of_any_kind_first(opencode_db, hermes_db, no_session_files):
    opencode_db({"id": "ses_older", "directory": "/work/app", "title": "", "time_created": 0,
                 "time_updated": int((time.time() - 7200) * 1000)})
    hermes_db({"id": "s_newer", "source": "cli", "cwd": "/work/app", "started_at": time.time() - 3600})

    found = sessions.recent_sessions(7)

    assert [session.session_id for session in found] == ["s_newer", "ses_older"]

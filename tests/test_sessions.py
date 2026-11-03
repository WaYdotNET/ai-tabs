"""Listing the recent omp and Claude Code sessions, and opening them with `ai-tabs sessions --open`."""

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_tabs import agents, cli, sessions
from ai_tabs.models import Agent, Pane, Tab, Window

OMP_ID = "01a19c67-8b23-7647-94a4-129e31e15632"
CLAUDE_ID = "647220e6-3b74-4d02-b279-166e97f3adde"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point the omp and Claude Code session folders at empty temporary folders."""
    omp_root, claude_root = tmp_path / "omp", tmp_path / "claude"
    monkeypatch.setattr(sessions, "OMP_SESSION_DIR", omp_root)
    monkeypatch.setattr(sessions, "CLAUDE_PROJECTS_DIR", claude_root)
    return omp_root, claude_root


@pytest.fixture
def opened(monkeypatch):
    """Replace the iTerm2 openers with fakes that record the windows, and say that iTerm2 runs."""
    calls = []
    monkeypatch.setattr(cli, "iterm_is_running", lambda: True)
    monkeypatch.setattr(cli, "open_in_new_windows", lambda windows: calls.append(("new", windows)))
    monkeypatch.setattr(cli, "open_in_current_window", lambda windows: calls.append(("here", windows)))
    return calls


def write_lines(path: Path, records: list[dict], age_days: float = 0.0) -> Path:
    """Write the records as JSON lines and set the file mtime to `age_days` days ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    moment = time.time() - age_days * 86400
    os.utime(path, (moment, moment))
    return path


def write_omp(root: Path, session_id: str = OMP_ID, title: str = "Fix the bug", age_days: float = 0.0) -> Path:
    """Write an omp session file with a title header, a session header and one message."""
    records = [{"type": "title", "title": title},
               {"type": "session", "id": session_id, "cwd": "/work/omp", "title": "old title"},
               {"type": "message", "text": "hello"}]
    return write_lines(root / "-work-omp" / f"2026-11-02T13-16-33-955Z_{session_id}.jsonl", records, age_days)


def write_claude(root: Path, records: list[dict], session_id: str = CLAUDE_ID, age_days: float = 0.0) -> Path:
    """Write a Claude Code session file named after its session ID."""
    return write_lines(root / "-work-claude" / f"{session_id}.jsonl", records, age_days)


def claude_records(*extra: dict) -> list[dict]:
    """Return the first records of a Claude Code session, then the extra records."""
    return [{"type": "mode", "mode": "normal"},
            {"type": "user", "cwd": "/work/claude", "message": {"role": "user", "content": "Add a sessions command"}},
            *extra]


def test_omp_session_reads_id_folder_and_title_from_headers(roots):
    omp_root, _ = roots
    path = write_omp(omp_root)

    found = sessions.recent_sessions(7)

    assert [(s.kind, s.session_id, s.cwd, s.title, s.path) for s in found] == [
        ("omp", OMP_ID, "/work/omp", "Fix the bug", path)]


def test_omp_helper_files_and_sub_folders_are_left_out(roots):
    omp_root, _ = roots
    write_lines(omp_root / "-work-omp" / "__advisor.jsonl", [{"type": "session", "id": "advisor", "cwd": "/x"}])
    write_lines(omp_root / "-work-omp" / "abc" / "task.jsonl", [{"type": "session", "id": "task", "cwd": "/x"}])

    found = sessions.recent_sessions(7)

    assert found == []


def test_claude_session_reads_folder_and_id_from_file_and_ai_title(roots):
    _, claude_root = roots
    write_claude(claude_root, claude_records({"type": "ai-title", "aiTitle": "Sessions command"}))

    found = sessions.recent_sessions(7)

    assert [(s.kind, s.session_id, s.cwd, s.title) for s in found] == [
        ("claude", CLAUDE_ID, "/work/claude", "Sessions command")]


def test_claude_custom_title_wins_over_ai_title(roots):
    _, claude_root = roots
    write_claude(claude_root, claude_records({"type": "custom-title", "customTitle": "My name"},
                                             {"type": "ai-title", "aiTitle": "Sessions command"}))

    found = sessions.recent_sessions(7)

    assert found[0].title == "My name"


def test_claude_title_falls_back_to_first_typed_prompt_cut_to_60_characters(roots):
    _, claude_root = roots
    command = {"content": "<command-message>plan</command-message>"}
    typed = {"content": [{"type": "text", "text": "x" * 70}]}
    records = [{"type": "user", "cwd": "/work/claude", "message": command},
               {"type": "user", "cwd": "/work/claude", "message": typed}]
    write_claude(claude_root, records)

    found = sessions.recent_sessions(7)

    assert found[0].title == "x" * 60


def test_claude_title_after_the_first_lines_comes_from_the_end_of_the_file(roots):
    _, claude_root = roots
    filler = [{"type": "mode", "mode": "normal"}] * 300
    write_claude(claude_root, claude_records(*filler, {"type": "custom-title", "customTitle": "Late name"}))

    found = sessions.recent_sessions(7)

    assert found[0].title == "Late name"


def test_claude_file_without_folder_is_left_out(roots):
    _, claude_root = roots
    write_claude(claude_root, [{"type": "mode", "mode": "normal"}])

    found = sessions.recent_sessions(7)

    assert found == []


def test_claude_sdk_sessions_are_left_out(roots):
    _, claude_root = roots
    sdk = [{"type": "user", "cwd": "/work/claude", "entrypoint": "sdk-py", "message": {"content": "Review this"}}]
    typed = [{"type": "user", "cwd": "/work/claude", "entrypoint": "cli", "message": {"content": "Add a command"}}]
    write_claude(claude_root, sdk, session_id="sdk-session")
    write_claude(claude_root, typed, session_id="cli-session")

    found = sessions.recent_sessions(7)

    assert [s.session_id for s in found] == ["cli-session"]


def test_running_sessions_are_left_out(roots, monkeypatch):
    omp_root, claude_root = roots
    write_omp(omp_root)
    write_claude(claude_root, claude_records())
    monkeypatch.setattr(agents, "running_sessions", lambda: frozenset({("omp", OMP_ID)}))

    found = sessions.recent_sessions(7)

    assert [s.session_id for s in found] == [CLAUDE_ID]


def test_days_leaves_out_files_older_than_the_limit(roots):
    omp_root, _ = roots
    write_omp(omp_root, session_id="old", age_days=4)
    write_omp(omp_root, session_id="new", age_days=2)

    found = sessions.recent_sessions(3)

    assert [s.session_id for s in found] == ["new"]


def test_newest_session_is_first(roots):
    omp_root, claude_root = roots
    write_omp(omp_root, age_days=2)
    write_claude(claude_root, claude_records(), age_days=1)

    found = sessions.recent_sessions(7)

    assert [s.session_id for s in found] == [CLAUDE_ID, OMP_ID]


def test_list_shows_short_id_and_title(roots):
    omp_root, _ = roots
    write_omp(omp_root)

    result = CliRunner().invoke(cli.app, ["sessions"])

    assert result.exit_code == 0
    assert "01a19c67" in result.output
    assert "Fix the bug" in result.output


def test_open_resumes_omp_session_in_a_new_window(roots, opened):
    omp_root, _ = roots
    path = write_omp(omp_root)

    result = CliRunner().invoke(cli.app, ["sessions", "--open", "01a1"])

    resume = f"cd /work/omp && omp --resume {path}"
    agent = Agent("omp", 0, "/work/omp", OMP_ID, "Fix the bug", resume)
    expected = Window([100.0, 100.0, 1200.0, 800.0], [Tab("Fix the bug", None, [Pane("omp", "", "/work/omp", agent)])])
    assert result.exit_code == 0
    assert opened == [("new", [expected])]


def test_open_resumes_claude_session_by_id(roots, opened):
    _, claude_root = roots
    write_claude(claude_root, claude_records())

    CliRunner().invoke(cli.app, ["sessions", "--open", "6472"])

    agent = opened[0][1][0].tabs[0].panes[0].agent
    assert agent.resume == f"cd /work/claude && claude --resume {CLAUDE_ID}"


def test_open_quotes_a_folder_with_spaces(roots, opened):
    _, claude_root = roots
    records = [{"type": "user", "cwd": "/my work", "message": {"content": "hello"}}]
    write_claude(claude_root, records)

    CliRunner().invoke(cli.app, ["sessions", "--open", "6472"])

    agent = opened[0][1][0].tabs[0].panes[0].agent
    assert agent.resume == f"cd '/my work' && claude --resume {CLAUDE_ID}"


def test_open_several_sessions_gives_one_window_with_one_tab_each(roots, opened):
    omp_root, claude_root = roots
    write_omp(omp_root, age_days=1)
    write_claude(claude_root, claude_records({"type": "ai-title", "aiTitle": "Sessions command"}))

    CliRunner().invoke(cli.app, ["sessions", "--open", "01a1", "--open", "6472"])

    windows = opened[0][1]
    assert [[tab.title for tab in window.tabs] for window in windows] == [["Fix the bug", "Sessions command"]]


def test_open_with_here_uses_the_current_window(roots, opened):
    omp_root, _ = roots
    write_omp(omp_root)

    CliRunner().invoke(cli.app, ["sessions", "--open", "01a1", "--here"])

    assert opened[0][0] == "here"


def test_open_with_ambiguous_prefix_is_an_error(roots, opened):
    omp_root, _ = roots
    write_omp(omp_root, session_id="01a1-one")
    write_omp(omp_root, session_id="01a1-two")

    result = CliRunner().invoke(cli.app, ["sessions", "--open", "01a1"])

    assert result.exit_code == 2
    assert "2 listed sessions start with '01a1'" in result.output
    assert opened == []


def test_open_with_unknown_prefix_is_an_error(roots, opened):
    omp_root, _ = roots
    write_omp(omp_root)

    result = CliRunner().invoke(cli.app, ["sessions", "--open", "ffff"])

    assert result.exit_code == 2
    assert "no listed session starts with 'ffff'" in result.output
    assert opened == []

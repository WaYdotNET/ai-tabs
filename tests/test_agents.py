"""Tests for the command line capture and the launch flags that a resumed session keeps."""

import json

from ai_tabs import agents


def test_claude_flags_keep_launch_settings():
    argv = ["claude", "--dangerously-skip-permissions", "--model", "opus", "--permission-mode", "plan"]

    flags = agents.claude_flags(argv)

    assert flags == "--dangerously-skip-permissions --model opus --permission-mode plan"


def test_claude_flags_drop_resume_continue_print_and_prompt():
    argv = ["claude", "--resume", "abc", "-c", "-p", "--verbose", "fix the bug"]

    flags = agents.claude_flags(argv)

    assert flags == "--verbose"


def test_claude_flags_keep_every_value_of_add_dir():
    argv = ["claude", "--add-dir", "/a", "/b c", "--ide"]

    flags = agents.claude_flags(argv)

    assert flags == "--add-dir /a '/b c' --ide"


def test_claude_flags_accept_the_equals_form():
    argv = ["claude", "--model=sonnet"]

    flags = agents.claude_flags(argv)

    assert flags == "--model sonnet"


def test_omp_flags_keep_equals_and_space_forms():
    argv = ["omp", "--model=opus", "--thinking", "high", "--auto-approve", "-e", "x.ts"]

    flags = agents.omp_flags(argv)

    assert flags == "--model=opus --thinking=high --auto-approve -e=x.ts"


def test_omp_flags_drop_session_flags_unknown_flags_and_prompt():
    argv = ["omp", "--resume", "/s.jsonl", "--continue", "--print", "--goal=ship", "--mystery", "--no-lsp", "hello"]

    flags = agents.omp_flags(argv)

    assert flags == "--no-lsp"


def test_omp_flags_keep_repeated_add_dir():
    argv = ["omp", "--add-dir=/a", "--add-dir", "/b"]

    flags = agents.omp_flags(argv)

    assert flags == "--add-dir=/a --add-dir=/b"


def test_redact_secrets_hides_api_key_in_equals_form():
    argv = ["omp", "--api-key=sk-123", "--model=opus"]

    redacted = agents.redact_secrets(argv)

    assert redacted == ["omp", "--api-key=***", "--model=opus"]


def test_redact_secrets_hides_api_key_in_space_form():
    argv = ["omp", "--api-key", "sk-123", "--auto-approve"]

    redacted = agents.redact_secrets(argv)

    assert redacted == ["omp", "--api-key", "***", "--auto-approve"]


def test_process_argv_splits_the_ps_output(monkeypatch):
    monkeypatch.setattr(agents, "run", lambda *command: "omp --model=opus a b\n")

    argv = agents.process_argv(42)

    assert argv == ["omp", "--model=opus", "a", "b"]


def test_omp_agent_resume_keeps_flags_and_stores_redacted_argv(tmp_path, monkeypatch):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(json.dumps({"type": "session", "id": "s1", "cwd": "/work"}) + "\n"
                            + json.dumps({"type": "title", "title": "t"}) + "\n")
    monkeypatch.setattr(agents, "omp_session_file", lambda pid: session_file)
    monkeypatch.setattr(agents, "run", lambda *command: "omp --model=opus --api-key=sk --auto-approve go")

    agent = agents.omp_agent(7)

    assert agent.resume == f"cd /work && omp --resume {session_file} --model=opus --auto-approve"
    assert agent.argv == ["omp", "--model=opus", "--api-key=***", "--auto-approve", "go"]


def test_claude_agent_resume_keeps_flags(tmp_path, monkeypatch):
    (tmp_path / "7.json").write_text(json.dumps({"sessionId": "id1", "cwd": "/work", "name": "n"}))
    monkeypatch.setattr(agents, "CLAUDE_PID_DIR", tmp_path)
    monkeypatch.setattr(agents, "run", lambda *command: "claude --dangerously-skip-permissions -r id1")

    agent = agents.claude_agent(7)

    assert agent.resume == "cd /work && claude --resume id1 --dangerously-skip-permissions"

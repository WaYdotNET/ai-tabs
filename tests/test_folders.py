"""Tests for the working folder of the foreground program of a pane."""

from ai_tabs import folders

PS_SLEEP = "  500   600   500 -zsh\n  600   600   600 sleep\n"
PS_PROMPT = "  500   500   500 -zsh\n  510   500   505 gitstatusd\n"
PS_PIPELINE = (
    "  500   700   500 /bin/zsh\n"
    "  650   650   650 vim\n"
    "  701   700   700 grep\n"
    "  700   700   700 tail\n"
    "  702   700   700 less\n"
)
LSOF_TMP = "p600\nfcwd\nn/tmp\n"


def fake_run(ps_output: str, lsof_outputs: dict[str, str]):
    """Return a `run` that answers `ps` with `ps_output` and `lsof` with the output for the PID."""

    def run(*command: str) -> str:
        if command[0] == folders.PS:
            return ps_output
        pid = command[command.index("-p") + 1]
        return lsof_outputs.get(pid, "")

    return run


def test_foreground_program_gives_its_cwd(monkeypatch):
    monkeypatch.setattr(folders, "run", fake_run(PS_SLEEP, {"600": LSOF_TMP}))

    folder = folders.pane_folder("/dev/ttys001", "/Users/me")

    assert folder == "/tmp"


def test_foreground_shell_keeps_the_iterm_path(monkeypatch):
    monkeypatch.setattr(folders, "run", fake_run(PS_PROMPT, {"500": "p500\nfcwd\nn/elsewhere\n"}))

    folder = folders.pane_folder("/dev/ttys001", "/Users/me/project")

    assert folder == "/Users/me/project"


def test_failed_lsof_keeps_the_iterm_path(monkeypatch):
    monkeypatch.setattr(folders, "run", fake_run(PS_SLEEP, {}))

    folder = folders.pane_folder("/dev/ttys001", "/Users/me")

    assert folder == "/Users/me"


def test_failed_ps_keeps_the_iterm_path(monkeypatch):
    monkeypatch.setattr(folders, "run", fake_run("", {"600": LSOF_TMP}))

    folder = folders.pane_folder("/dev/ttys001", "/Users/me")

    assert folder == "/Users/me"


def test_tpgid_match_picks_the_foreground_group_leader():
    processes = [folders.parse_process(line) for line in PS_PIPELINE.splitlines()]

    process = folders.foreground_process(processes)

    assert process.pid == 700


def test_without_tpgid_match_the_newest_process_wins():
    processes = [folders.TtyProcess(500, 900, 500, "zsh"), folders.TtyProcess(650, 900, 650, "vim")]

    process = folders.foreground_process(processes)

    assert process.pid == 650


def test_ps_runs_on_the_tty_name_without_dev(monkeypatch):
    calls = []
    monkeypatch.setattr(folders, "run", lambda *command: calls.append(command) or "")

    folders.tty_processes("/dev/ttys004")

    assert calls == [(folders.PS, "-o", "pid=,tpgid=,pgid=,comm=", "-t", "ttys004")]


def test_command_name_with_spaces_stays_whole():
    process = folders.parse_process("  42  42  42 /Applications/My App/bin/tool")

    assert process == folders.TtyProcess(42, 42, 42, "/Applications/My App/bin/tool")


def test_no_tty_keeps_the_iterm_path(monkeypatch):
    monkeypatch.setattr(folders, "run", fake_run(PS_SLEEP, {"600": LSOF_TMP}))

    folder = folders.pane_folder("", "/Users/me")

    assert folder == "/Users/me"

"""Small builders for snapshot data. Each one sets only the fields that a test cares about."""

from ai_tabs.models import Agent, Pane, Tab, Window


def agent(session_id: str, title: str = "work", kind: str = "omp") -> Agent:
    """Return an agent session with a fixed folder and resume command."""
    return Agent(kind, 100, "/work", session_id, title, f"cd /work && {kind} --resume {session_id}")


def shell_pane(tty: str = "/dev/ttys001", path: str = "/work") -> Pane:
    """Return a pane that runs a shell only."""
    return Pane("zsh", tty, path)


def agent_pane(session_id: str, title: str = "work") -> Pane:
    """Return a pane that runs an omp session."""
    return Pane("omp", "/dev/ttys002", "/work", agent(session_id, title))


def tab(*panes: Pane, title: str = "") -> Tab:
    """Return a tab with the panes, without a color."""
    return Tab(title, None, list(panes))


def windows_with_tabs(count: int) -> list[Window]:
    """Return one window with `count` shell tabs, each on its own tty."""
    return [Window([0, 0, 800, 600], [tab(shell_pane(f"/dev/ttys{index:03}")) for index in range(count)])]


def sized_window(frame: list[float], columns: int, rows: int) -> Window:
    """Return one window with one shell tab, whose pane has the size `columns` x `rows`."""
    return Window(frame, [tab(Pane("zsh", "/dev/ttys001", "/work", columns=columns, rows=rows))])

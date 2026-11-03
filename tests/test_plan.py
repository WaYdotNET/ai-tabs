"""Tests for the guard that resumes each agent session in one pane only, and for running sessions."""

import copy
from functools import cache

from factories import agent_pane, tab

from ai_tabs import agents
from ai_tabs.models import Window
from ai_tabs.plan import fresh_pane_commands, pane_command, plan_text, resolve_duplicates


def two_tabs_same_session() -> list[Window]:
    """Return one window whose two tabs run the same omp session s1."""
    return [Window([0, 0, 800, 600], [tab(agent_pane("s1"), title="a"), tab(agent_pane("s1"), title="b")])]


def test_first_pane_keeps_its_resume():
    windows = two_tabs_same_session()

    resolved = resolve_duplicates(windows)

    assert resolved[0].tabs[0].panes[0].agent.resume == "cd /work && omp --resume s1"


def test_later_pane_only_opens_the_folder():
    windows = two_tabs_same_session()

    resolved = resolve_duplicates(windows)

    assert resolved[0].tabs[1].panes[0].agent.resume == "cd /work  # omp session s1 is also in tab 1.1"


def test_input_windows_stay_unchanged():
    windows = two_tabs_same_session()
    before = copy.deepcopy(windows)

    resolve_duplicates(windows)

    assert windows == before


def test_plan_text_shows_the_duplicate_comment():
    windows = resolve_duplicates(two_tabs_same_session())

    text = plan_text(windows, ["1.2"]).plain

    assert text == "b  1.2\n  cd /work  # omp session s1 is also in tab 1.1"


def test_a_session_that_stops_after_the_screen_opens_resumes(monkeypatch):
    running = {("omp", "s1")}
    monkeypatch.setattr(agents, "running_sessions", cache(lambda: frozenset(running)))
    pane = agent_pane("s1")
    on_screen = pane_command(pane)
    running.clear()

    commands = fresh_pane_commands([pane])

    assert on_screen == "cd /work  # omp session s1 still runs"
    assert commands == ["cd /work && omp --resume s1"]

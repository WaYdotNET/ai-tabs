"""The history index: reading every snapshot, matching tabs and grouping them into entries."""

from datetime import datetime

from factories import agent_pane, shell_pane, tab

from ai_tabs import history, store
from ai_tabs.models import Agent, Pane, Tab, Window

NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def index_of(*snapshots: tuple[datetime, list[Tab]]) -> history.HistoryIndex:
    """Store each snapshot as one window with the given tabs, then read the history index."""
    for moment, tabs in snapshots:
        store.insert_snapshot([Window([0, 0, 800, 600], tabs)], NO_CHANGES, moment)
    return history.read_index()


def test_read_index_counts_every_snapshot_and_lists_the_newest_first():
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [tab(shell_pane(), title="OLD")]),
                     (datetime(2026, 11, 2, 11, 0, 0), []))
    assert index.snapshot_count == 2
    assert [o.summary.id for o in index.occurrences] == ["2026-11-02/10-00-00"]


def test_an_agent_session_with_a_new_title_is_one_entry_with_two_variants():
    index = index_of(
        (datetime(2026, 11, 2, 15, 9, 4), [tab(agent_pane("01a1156d", "Fz bus event api plan"), title="DAPR")]),
        (datetime(2026, 11, 2, 16, 16, 46), [tab(agent_pane("01a1156d", "dapr"), title="DAPR")]),
    )
    [entry] = history.search(index, "dapr")
    assert [v.text for v in entry.variants] == [("DAPR", "dapr"), ("DAPR", "Fz bus event api plan")]
    assert [s.id for s in entry.summaries] == ["2026-11-02/16-16-46", "2026-11-02/15-09-04"]


def test_shell_tabs_in_one_folder_with_another_title_are_two_entries():
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(shell_pane(path="/home"), title="DAPR"),
        tab(Pane("dapr (omp)", "/dev/ttys003", "/home")),
    ]))
    assert len(history.search(index, "dapr")) == 2


def test_the_shell_panes_of_an_agent_tab_do_not_split_it():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"), Pane("zsh", "/dev/ttys003", "/a"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(agent_pane("s1", "dapr"), Pane("git (less)", "/dev/ttys003", "/b"))]),
    )
    [entry] = history.search(index, "dapr")
    assert len(entry.variants) == 1
    assert len(entry.summaries) == 2


def test_two_tabs_with_one_key_in_one_snapshot_count_once_and_restore_the_first():
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(shell_pane("/dev/ttys001", "/dapr")),
        tab(shell_pane("/dev/ttys002", "/dapr")),
    ]))
    [entry] = history.search(index, "dapr")
    assert [s.id for s in entry.summaries] == ["2026-11-02/10-00-00"]
    assert history.restore_position(entry, "2026-11-02/10-00-00") == "1.1"


def test_a_variant_restores_the_tab_with_its_own_text():
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(agent_pane("s1", "dapr"), title="A"),
        tab(agent_pane("s1", "dapr"), title="B"),
    ]))
    [entry] = history.search(index, "dapr")
    variant_b = next(v for v in entry.variants if v.text[0] == "B")
    assert history.restore_position(variant_b, "2026-11-02/10-00-00") == "1.2"
    assert history.restore_position(entry, "2026-11-02/10-00-00") == "1.1"


def test_the_counts_include_only_the_occurrences_that_match():
    index = index_of(
        (datetime(2026, 11, 2, 15, 9, 0), [tab(agent_pane("s1", "plan"))]),
        (datetime(2026, 11, 2, 16, 16, 0), [tab(agent_pane("s1", "dapr"))]),
    )
    [entry] = history.search(index, "dapr")
    assert [s.id for s in entry.summaries] == ["2026-11-02/16-16-00"]


def test_agent_entries_come_first_then_the_newest_entry():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"), title="AGENT")]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(shell_pane(path="/old/dapr"), title="OLD")]),
        (datetime(2026, 11, 2, 12, 0, 0), [tab(shell_pane(path="/new/dapr"), title="NEW")]),
    )
    assert [e.newest.tab.title for e in history.search(index, "dapr")] == ["AGENT", "NEW", "OLD"]


def test_a_blank_query_finds_nothing():
    index = index_of()
    assert history.search(index, "  ") == []


def test_two_agents_without_a_session_id_are_two_entries():
    agent_a = Agent("omp", 1, "/work", "", "dapr", "omp --resume /a.jsonl")
    agent_b = Agent("omp", 1, "/work", "", "dapr", "omp --resume /b.jsonl")
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(Pane("omp", "/dev/ttys002", "/work", agent_a)),
        tab(Pane("omp", "/dev/ttys002", "/work", agent_b)),
    ]))
    assert len(history.search(index, "dapr")) == 2

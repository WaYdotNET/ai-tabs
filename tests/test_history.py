"""The history index: reading every snapshot, matching tabs and grouping them into entries."""

from datetime import datetime

from factories import agent_pane, shell_pane, tab
from rich.text import Text

from ai_tabs import agents, display, history, store
from ai_tabs.models import Agent, Pane, Tab, Window
from ai_tabs.palette import DARK

NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def index_of(*snapshots: tuple[datetime, list[Tab]]) -> history.HistoryIndex:
    """Store each snapshot as one window with the given tabs, then read the history index."""
    for moment, tabs in snapshots:
        store.insert_snapshot([Window([0, 0, 800, 600], tabs)], NO_CHANGES, moment)
    return history.read_index()


def entry_lines(entry: history.Entry) -> list[str]:
    """Return the plain lines of the collapsed view of an entry, searched with `dapr`."""
    return Text.from_markup(display.entry_markup(entry, "dapr", DARK)).plain.split("\n")


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

    entries = history.search(index, "dapr")

    assert len(entries) == 2


def agent_tab_with_two_shell_panes() -> history.HistoryIndex:
    """Return the index of two snapshots that hold one agent tab with a shell pane in another folder."""
    return index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"), Pane("zsh", "/dev/ttys003", "/a"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(agent_pane("s1", "dapr"), Pane("git (less)", "/dev/ttys003", "/b"))]),
    )


def test_the_shell_panes_of_an_agent_tab_do_not_add_a_variant():
    index = agent_tab_with_two_shell_panes()

    [entry] = history.search(index, "dapr")

    assert len(entry.variants) == 1


def test_the_shell_panes_of_an_agent_tab_do_not_split_its_snapshots():
    index = agent_tab_with_two_shell_panes()

    [entry] = history.search(index, "dapr")

    assert [s.id for s in entry.summaries] == ["2026-11-02/11-00-00", "2026-11-02/10-00-00"]


def two_shell_tabs_in_one_snapshot() -> history.HistoryIndex:
    """Return the index of one snapshot that holds two shell tabs with the same folder."""
    return index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(shell_pane("/dev/ttys001", "/dapr")),
        tab(shell_pane("/dev/ttys002", "/dapr")),
    ]))


def test_two_tabs_with_one_key_in_one_snapshot_count_the_snapshot_once():
    index = two_shell_tabs_in_one_snapshot()

    [entry] = history.search(index, "dapr")

    assert [s.id for s in entry.summaries] == ["2026-11-02/10-00-00"]


def test_two_tabs_with_one_key_in_one_snapshot_restore_the_first_of_them():
    index = two_shell_tabs_in_one_snapshot()

    [entry] = history.search(index, "dapr")

    assert history.restore_position(entry, "2026-11-02/10-00-00") == "1.1"


def two_agent_tabs_with_one_session() -> history.HistoryIndex:
    """Return the index of one snapshot that holds the same agent session in two tabs, A and B."""
    return index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(agent_pane("s1", "dapr"), title="A"),
        tab(agent_pane("s1", "dapr"), title="B"),
    ]))


def test_a_variant_restores_the_tab_with_its_own_text():
    index = two_agent_tabs_with_one_session()

    [entry] = history.search(index, "dapr")

    assert history.restore_position(entry.variants[1], "2026-11-02/10-00-00") == "1.2"


def test_an_entry_restores_the_first_tab_of_the_snapshot():
    index = two_agent_tabs_with_one_session()

    [entry] = history.search(index, "dapr")

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

    entries = history.search(index, "dapr")

    assert [e.newest.tab.title for e in entries] == ["AGENT", "NEW", "OLD"]


def test_a_blank_query_finds_nothing():
    index = index_of()

    entries = history.search(index, "  ")

    assert entries == []


def test_two_agents_without_a_session_id_are_two_entries():
    agent_a = Agent("omp", 1, "/work", "", "dapr", "omp --resume /a.jsonl")
    agent_b = Agent("omp", 1, "/work", "", "dapr", "omp --resume /b.jsonl")
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [
        tab(Pane("omp", "/dev/ttys002", "/work", agent_a)),
        tab(Pane("omp", "/dev/ttys002", "/work", agent_b)),
    ]))

    entries = history.search(index, "dapr")

    assert len(entries) == 2


def test_period_on_one_day_shows_the_day_once():
    first, last = datetime(2026, 11, 2, 15, 9, 4), datetime(2026, 11, 2, 21, 48, 18)

    moment = display.period(first, last)

    assert moment == "11-02 15:09 → 21:48"


def test_period_over_two_days_shows_both_days():
    first, last = datetime(2026, 11, 2, 22, 26, 26), datetime(2026, 11, 3, 12, 28, 51)

    moment = display.period(first, last)

    assert moment == "11-02 22:26 → 11-03 12:28"


def test_one_snapshot_is_counted_in_the_singular():
    assert display.counted_snapshots(1) == "1 snapshot"


def test_two_snapshots_are_counted_in_the_plural():
    assert display.counted_snapshots(2) == "2 snapshots"


def test_no_snapshot_is_counted_in_the_plural():
    assert display.counted_snapshots(0) == "0 snapshots"


def test_highlight_marks_a_word_without_regard_to_case():
    assert display.highlight("DAPR plan", "dapr", "#fff") == "[bold underline #fff]DAPR[/] plan"


def test_highlight_escapes_markup_in_the_text():
    assert display.highlight("[wip] dapr", "dapr", "#fff") == "\\[wip] [bold underline #fff]dapr[/]"


def test_agent_entry_lists_the_older_titles_newest_first():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "a"), title="DAPR")]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(agent_pane("s1", "b"), title="DAPR")]),
        (datetime(2026, 11, 2, 12, 0, 0), [tab(agent_pane("s1", "c"), title="DAPR")]),
    )
    entry = history.search(index, "dapr")[0]

    lines = entry_lines(entry)

    assert lines[1] == "    c   was: b, a"


def test_an_entry_with_a_running_session_shows_the_green_dot(monkeypatch):
    monkeypatch.setattr(agents, "running_sessions", lambda: frozenset({("omp", "s1")}))
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"))]))
    entry = history.search(index, "dapr")[0]

    lines = entry_lines(entry)

    assert lines[0] == "  dapr  ● omp"


def test_entry_shows_the_pin_only_when_its_newest_snapshot_is_pinned():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(agent_pane("s1", "dapr"))]),
    )
    older_id = index.occurrences[-1].summary.id

    store.set_pin(older_id, "manual")
    entry = history.search(history.read_index(), "dapr")[0]

    assert "📌" not in "\n".join(entry_lines(entry))


def test_entry_shows_the_pin_of_its_newest_snapshot():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(agent_pane("s1", "dapr"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(agent_pane("s1", "dapr"))]),
    )
    newest_id = index.occurrences[0].summary.id

    store.set_pin(newest_id, "before-boot")
    entry = history.search(history.read_index(), "dapr")[0]

    assert entry_lines(entry)[-1] == "    11-02 10:00 → 11:00 · 2 snapshots · last 📌 before boot"


def test_shell_entry_lists_its_distinct_names_newest_first():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(Pane("zsh", "/dev/ttys001", "/dapr"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(Pane("pulumi", "/dev/ttys001", "/dapr"))]),
        (datetime(2026, 11, 2, 12, 0, 0), [tab(Pane("zsh", "/dev/ttys001", "/dapr"))]),
    )
    entry = history.search(index, "dapr")[0]

    lines = entry_lines(entry)

    assert lines[1] == "    /dapr · names: zsh, pulumi"


def test_period_line_has_the_same_indent_as_the_lines_above_it():
    index = index_of(
        (datetime(2026, 11, 2, 10, 0, 0), [tab(Pane("zsh", "/dev/ttys001", "/dapr"))]),
        (datetime(2026, 11, 2, 11, 0, 0), [tab(Pane("zsh", "/dev/ttys001", "/dapr"))]),
    )
    entry = history.search(index, "dapr")[0]

    lines = entry_lines(entry)

    assert lines[-1] == "    11-02 10:00 → 11:00 · 2 snapshots"


def test_variant_markup_shows_each_distinct_part_once():
    index = index_of((datetime(2026, 11, 2, 10, 0, 0), [tab(Pane("zsh", "/dev/ttys001", "/dapr"))]))
    variant = history.search(index, "dapr")[0].variants[0]

    line = Text.from_markup(display.variant_markup(variant, True, "dapr", DARK)).plain

    assert line == "      └ zsh                     11-02 10:00 → 10:00 · 1 snapshot"

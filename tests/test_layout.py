"""The split layout of a tab: how a snapshot reads it and how a restore rebuilds it."""

from types import SimpleNamespace

from ai_tabs.iterm import layout_tree
from ai_tabs.opener import known_profile, split_steps


def splitter(vertical: bool, *children: SimpleNamespace) -> SimpleNamespace:
    """Return a fake iTerm2 splitter with the children."""
    return SimpleNamespace(vertical=vertical, children=list(children))


def session() -> SimpleNamespace:
    """Return a fake iTerm2 session: an object without children."""
    return SimpleNamespace()


NESTED_LAYOUT = {"vertical": True, "children": [
    {"pane": 0},
    {"vertical": False, "children": [{"pane": 1}, {"pane": 2}]},
]}


def test_a_tab_with_one_pane_has_no_layout():
    root = splitter(True, session())

    layout = layout_tree(root)

    assert layout is None


def test_nested_splitters_give_a_nested_layout_numbered_depth_first():
    root = splitter(True, session(), splitter(False, session(), session()))

    layout = layout_tree(root)

    assert layout == NESTED_LAYOUT


def test_a_nested_layout_splits_siblings_first_then_inside_each_child():
    steps = split_steps(NESTED_LAYOUT, 3)

    assert steps == [(0, 1, True), (1, 2, False)]


def test_a_node_as_first_child_splits_from_its_first_pane():
    layout = {"vertical": True, "children": [
        {"vertical": False, "children": [{"pane": 0}, {"pane": 1}]},
        {"pane": 2},
    ]}

    steps = split_steps(layout, 3)

    assert steps == [(0, 2, True), (0, 1, False)]


def test_panes_without_a_layout_open_side_by_side():
    steps = split_steps(None, 3)

    assert steps == [(0, 1, True), (1, 2, True)]


def test_an_unknown_profile_falls_back_to_the_default_profile():
    profile = known_profile("Gone", frozenset({"Default", "Work"}))

    assert profile is None


def test_a_known_profile_keeps_its_name():
    profile = known_profile("Work", frozenset({"Default", "Work"}))

    assert profile == "Work"

"""The history index: every tab occurrence of every snapshot, matched and grouped.

Pure logic, no Textual code. `HistoryScreen` consumes `read_index`, `search` and
`restore_position`.
"""

from dataclasses import dataclass

from .display import tab_heading, tab_matches
from .models import Pane, Tab, positioned_tabs
from .store import Summary, all_snapshots


@dataclass(frozen=True)
class Occurrence:
    """One tab, in one snapshot, at one position."""

    summary: Summary
    position: str
    tab: Tab


@dataclass(frozen=True)
class HistoryIndex:
    """Every tab occurrence of every snapshot, newest snapshot first.

    `snapshot_count` counts every snapshot, including the ones without tabs.
    """

    occurrences: tuple[Occurrence, ...]
    snapshot_count: int


@dataclass(frozen=True)
class Variant:
    """The occurrences of an entry that share the same visible text, newest first."""

    text: tuple[str, ...]
    occurrences: tuple[Occurrence, ...]

    @property
    def summaries(self) -> tuple[Summary, ...]:
        """Return the distinct snapshots of the variant, newest first."""
        return _distinct_summaries(self.occurrences)


@dataclass(frozen=True)
class Entry:
    """One distinct tab, grouped from every snapshot that holds it."""

    key: tuple
    variants: tuple[Variant, ...]

    @property
    def occurrences(self) -> tuple[Occurrence, ...]:
        """Return every occurrence of the entry, newest snapshot first."""
        pooled = [occurrence for variant in self.variants for occurrence in variant.occurrences]
        by_position = sorted(pooled, key=_position_order)
        return tuple(sorted(by_position, key=lambda occurrence: occurrence.summary.id, reverse=True))

    @property
    def summaries(self) -> tuple[Summary, ...]:
        """Return the distinct snapshots of the entry, newest first."""
        return _distinct_summaries(self.occurrences)

    @property
    def newest(self) -> Occurrence:
        """Return the newest occurrence of the entry."""
        return self.occurrences[0]

    @property
    def has_agent(self) -> bool:
        """Tell if the entry's tab runs an agent."""
        return any(pane.agent for pane in self.newest.tab.panes)


@dataclass(frozen=True)
class HistoryPick:
    """What `HistoryScreen` returns: the snapshot and the position to restore."""

    snapshot_id: str
    position: str


def _distinct_summaries(occurrences: tuple[Occurrence, ...]) -> tuple[Summary, ...]:
    """Return the distinct snapshots of a newest-first occurrence list, newest first."""
    by_id: dict[str, Summary] = {}
    for occurrence in occurrences:
        by_id.setdefault(occurrence.summary.id, occurrence.summary)
    return tuple(by_id.values())


def _position_order(occurrence: Occurrence) -> tuple[int, int]:
    """Return an occurrence's WINDOW.TAB position as a pair of numbers, for a numeric sort."""
    window, tab_index = occurrence.position.split(".")
    return (int(window), int(tab_index))


def _pane_key(pane: Pane) -> tuple:
    """Return the identity of a pane: its agent session, or its folder."""
    if pane.agent:
        return ("agent", pane.agent.kind, pane.agent.session_id or pane.agent.resume)
    return ("shell", pane.path)


def tab_key(tab: Tab) -> tuple:
    """Return the identity of a tab: its agent panes in order, or its title and every pane."""
    agent_panes = [pane for pane in tab.panes if pane.agent]
    if agent_panes:
        return tuple(_pane_key(pane) for pane in agent_panes)
    return (tab.title, *(_pane_key(pane) for pane in tab.panes))


def variant_text(tab: Tab) -> tuple[str, ...]:
    """Return the visible text of a tab: its heading, then the agent titles or the pane names."""
    agents = [pane.agent for pane in tab.panes if pane.agent]
    if agents:
        return (tab_heading(tab), *(agent.title for agent in agents))
    return (tab_heading(tab), *(pane.name for pane in tab.panes))


def read_index() -> HistoryIndex:
    """Read every snapshot and build the index of their tab occurrences, newest snapshot first."""
    snapshots = all_snapshots()
    occurrences = tuple(
        Occurrence(snapshot.summary, position, tab)
        for snapshot in snapshots
        for position, tab in positioned_tabs(snapshot.windows)
    )
    return HistoryIndex(occurrences, len(snapshots))


def _grouped_variants(occurrences: list[Occurrence]) -> tuple[Variant, ...]:
    """Group a tab key's occurrences into variants by their visible text, newest first."""
    by_text: dict[tuple[str, ...], list[Occurrence]] = {}
    for occurrence in occurrences:
        by_text.setdefault(variant_text(occurrence.tab), []).append(occurrence)
    return tuple(Variant(text, tuple(group)) for text, group in by_text.items())


def _grouped_entries(matches: list[Occurrence]) -> list[Entry]:
    """Group matching occurrences into entries by tab key, newest-occurrence-first order."""
    by_key: dict[tuple, list[Occurrence]] = {}
    for occurrence in matches:
        by_key.setdefault(tab_key(occurrence.tab), []).append(occurrence)
    return [Entry(key, _grouped_variants(occurrences)) for key, occurrences in by_key.items()]


def _ordered_entries(entries: list[Entry]) -> list[Entry]:
    """Sort entries with an agent first, keeping the newest-first order inside each group."""
    return sorted(entries, key=lambda entry: not entry.has_agent)


def search(index: HistoryIndex, query: str) -> list[Entry]:
    """Return the entries whose tab matches the query: agent entries first, newest first.

    A blank query matches nothing.
    """
    if not query.strip():
        return []
    matches = [occurrence for occurrence in index.occurrences if tab_matches(occurrence.tab, query)]
    return _ordered_entries(_grouped_entries(matches))


def restore_position(group: Entry | Variant, snapshot_id: str) -> str:
    """Return the WINDOW.TAB position that restores the group's tab from one snapshot."""
    candidates = [occurrence for occurrence in group.occurrences if occurrence.summary.id == snapshot_id]
    return min(candidates, key=_position_order).position

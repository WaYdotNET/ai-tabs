"""The history screen: one search over the tabs of all the snapshots, with the copies of a tab grouped."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, OptionList
from textual.widgets.option_list import Option

from .display import counted_snapshots, entry_markup, snapshot_markup, variant_markup
from .history import Entry, HistoryIndex, HistoryPick, Variant, restore_position, search
from .palette import Palette
from .store import Summary

READING = "Reading the snapshots…"
TYPE_QUERY = "Type to search all the snapshots."


@dataclass(frozen=True)
class Row:
    """One line of the result list: an entry, or one variant of an expanded entry."""

    entry: int
    variant: int | None


class HistoryScreen(Screen[HistoryPick | None]):
    """A search over every snapshot: the entries on the right, the snapshots of one entry on the left."""

    CSS = """
    #snapshots { width: 30; border: round $primary; text-wrap: nowrap; text-overflow: ellipsis; }
    #right { border: round $primary; }
    #results { height: 1fr; border: none; text-wrap: nowrap; text-overflow: ellipsis; }
    #filter { border: none; height: 1; padding: 0 1; }
    """
    BINDINGS = [
        Binding("enter", "restore", "restore", priority=True),
        Binding("tab,shift+tab", "switch_panel", "pick snapshot", priority=True),
        Binding("right", "expand", "variants", show=False),
        Binding("left", "collapse", "collapse", show=False),
        Binding("f", "dismiss(None)", "back"),
        Binding("escape", "leave", "leave"),
    ]

    def __init__(self, load: Callable[[], HistoryIndex], colors: Palette) -> None:
        """Keep the function that reads the index, and the colors of the entries."""
        super().__init__()
        self.load = load
        self.palette = colors
        self.history: HistoryIndex | None = None
        self.entries: list[Entry] = []
        self.rows: list[Row] = []
        self.expanded: set[tuple] = set()
        self.summaries: list[Summary] = []

    def compose(self) -> ComposeResult:
        """Lay out the snapshot list, the search field and the result list."""
        with Horizontal():
            yield OptionList(id="snapshots")
            with Vertical(id="right"):
                yield Input(placeholder="> search the tabs of all the snapshots", id="filter")
                yield OptionList(id="results")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the search field, show the loading hint and read the index in a thread."""
        self.query_one("#filter").focus()
        self.show_rows(None)
        self.read_in_background()

    @work(thread=True)
    def read_in_background(self) -> None:
        """Read every snapshot in a worker thread, because the parse of a long history takes time."""
        index = self.load()
        self.app.call_from_thread(self.after_index, index)

    def after_index(self, index: HistoryIndex) -> None:
        """Keep the index and show the results of the current query.

        The worker ends after a fast escape too, and then the screen is gone.
        """
        if not self.is_attached:
            return
        self.history = index
        self.show_results()

    def query_text(self) -> str:
        """Return the text of the search field."""
        return self.query_one("#filter", Input).value

    def show_results(self) -> None:
        """Search the index again and show the entries, with the first one highlighted."""
        self.entries = search(self.history, self.query_text()) if self.history else []
        self.show_rows(0)

    def listed_rows(self) -> Iterator[Row]:
        """Yield one row for each entry, and one more for each variant of an expanded entry."""
        for number, entry in enumerate(self.entries):
            yield Row(number, None)
            if entry.key in self.expanded:
                yield from (Row(number, index) for index in range(len(entry.variants)))

    def show_rows(self, highlighted: int | None) -> None:
        """Fill the result list with the rows, and highlight one of them."""
        self.rows = list(self.listed_rows())
        results = self.query_one("#results", OptionList)
        results.clear_options()
        results.add_options([self.row_option(row) for row in self.rows] or self.hint_options())
        results.highlighted = highlighted if self.rows else None
        self.paint_titles()
        if not self.rows:
            # An empty list highlights nothing, and a missing highlight posts no message.
            self.call_next(self.show_snapshots)

    def hint_options(self) -> list[Option]:
        """Return the line that stands for an empty result list. Enter ignores a disabled option."""
        if self.history is None:
            return [Option(Text(READING), disabled=True)]
        if not self.query_text().strip():
            return [Option(Text(TYPE_QUERY), disabled=True)]
        return []

    def row_option(self, row: Row) -> Option:
        """Return the option of one row: the collapsed entry, or the line of one variant."""
        entry = self.entries[row.entry]
        if row.variant is None:
            # The blank last line separates the entries.
            markup = entry_markup(entry, self.query_text(), self.palette) + "\n"
            return Option(Text.from_markup(markup), id=str(row.entry))
        last = row.variant == len(entry.variants) - 1
        markup = variant_markup(entry.variants[row.variant], last, self.query_text(), self.palette)
        return Option(Text.from_markup(markup), id=f"{row.entry}/{row.variant}")

    def current_row(self) -> Row | None:
        """Return the highlighted row, or None when the result list shows no row."""
        highlighted = self.query_one("#results", OptionList).highlighted
        if highlighted is None or highlighted >= len(self.rows):
            return None
        return self.rows[highlighted]

    def group_of(self, row: Row) -> Entry | Variant:
        """Return the entry of a row, or its variant when the row is a variant line."""
        entry = self.entries[row.entry]
        return entry if row.variant is None else entry.variants[row.variant]

    def current_snapshot(self) -> Summary | None:
        """Return the highlighted snapshot of the highlighted group.

        The snapshots come from the group, because the left list fills later.
        """
        row = self.current_row()
        if row is None:
            return None
        return self.snapshot_at(self.group_of(row).summaries)

    def snapshot_at(self, summaries: tuple[Summary, ...]) -> Summary | None:
        """Return the snapshot that the left list highlights, or the newest one when the index is too high."""
        index = self.query_one("#snapshots", OptionList).highlighted or 0
        if not summaries:
            return None
        return summaries[index] if index < len(summaries) else summaries[0]

    def snapshot_options(self) -> list[Option]:
        """Return one option of the snapshot list for each snapshot of the highlighted group."""
        # The blank last line separates the snapshots, as in the restore screen list.
        return [Option(Text.from_markup(snapshot_markup(summary, False, self.palette) + "\n"), id=summary.id)
                for summary in self.summaries]

    def paint_titles(self) -> None:
        """Show on the borders the number of matches, the snapshots of the group and the restore target."""
        count = self.history.snapshot_count if self.history else 0
        self.query_one("#right").border_title = f"History · {len(self.entries)} tabs match in {count} snapshots"
        self.query_one("#right").border_subtitle = self.restore_line()
        self.query_one("#snapshots").border_title = f"This tab · {counted_snapshots(len(self.summaries))}"

    def restore_line(self) -> str:
        """Return the subtitle: the place of the entry in the results, and the snapshot that Enter uses."""
        row, summary = self.current_row(), self.current_snapshot()
        if row is None or summary is None:
            return ""
        return f"{row.entry + 1} of {len(self.entries)} · restore from {summary.created_at:%H:%M:%S %m-%d}"

    def show_snapshots(self) -> None:
        """Fill the snapshot list with the snapshots of the highlighted group, newest first."""
        row = self.current_row()
        self.summaries = list(self.group_of(row).summaries) if row is not None else []
        snapshots = self.query_one("#snapshots", OptionList)
        snapshots.clear_options()
        snapshots.add_options(self.snapshot_options())
        snapshots.highlighted = 0 if self.summaries else None
        self.paint_titles()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Follow the highlight: the result list changes the snapshots, the snapshot list changes the subtitle."""
        if event.option_list.id == "snapshots":
            self.query_one("#right").border_subtitle = self.restore_line()
            return
        self.show_snapshots()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Search again while the text of the search field changes."""
        self.show_results()

    def row_of_entry(self, entry: int) -> int:
        """Return the row number of the collapsed line of an entry."""
        return list(self.listed_rows()).index(Row(entry, None))

    def action_expand(self) -> None:
        """Show the variants of the highlighted entry."""
        row = self.current_row()
        if row is None:
            return
        self.expanded.add(self.entries[row.entry].key)
        self.show_rows(self.row_of_entry(row.entry))

    def action_collapse(self) -> None:
        """Hide the variants of the highlighted entry."""
        row = self.current_row()
        if row is None:
            return
        self.expanded.discard(self.entries[row.entry].key)
        self.show_rows(self.row_of_entry(row.entry))

    def action_switch_panel(self) -> None:
        """Move the focus between the result list and the snapshot list."""
        snapshots = self.query_one("#snapshots")
        (self.query_one("#results") if self.focused is snapshots else snapshots).focus()

    def action_leave(self) -> None:
        """Leave the search field, or close the screen when the focus is already on a list."""
        if self.focused is self.query_one("#filter"):
            self.query_one("#results").focus()
            return
        self.dismiss(None)

    def action_restore(self) -> None:
        """Close the screen with the highlighted tab, taken from the highlighted snapshot."""
        row, summary = self.current_row(), self.current_snapshot()
        if row is None or summary is None:
            return
        self.dismiss(HistoryPick(summary.id, restore_position(self.group_of(row), summary.id)))

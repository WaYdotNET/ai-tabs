"""Lists over the restore screen: the recent sessions to resume, and the named layouts to open."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable

from .display import short_path
from .layouts import Layout
from .models import agent_count, tab_count
from .palette import Palette
from .sessions import SHORT_ID_LENGTH, Session

# The check, ID, kind and time columns, the cell padding of six columns, the box border and the scrollbar.
SESSION_FIXED_WIDTH = 1 + SHORT_ID_LENGTH + 6 + 11 + 12 + 2 + 2
MIN_TEXT_WIDTH = 12
# The list box takes 90% of the screen width.
BOX_PERCENT = 90
CHECK_COLUMN = 0


def cut_cell(value: str) -> Text:
    """Return a cell text that stays on one line and ends with an ellipsis when it is too long."""
    return Text(value, no_wrap=True, overflow="ellipsis")


def text_column_width(screen_width: int) -> int:
    """Return the width of the folder column and of the title column, for a screen `screen_width` characters wide."""
    box_width = screen_width * BOX_PERCENT // 100
    return max((box_width - SESSION_FIXED_WIDTH) // 2, MIN_TEXT_WIDTH)


class Picker[T](ModalScreen[T | None]):
    """A list in a box over the restore screen. Escape closes it without a result."""

    DEFAULT_CSS = f"""
    Picker {{ align: center middle; }}
    #picker {{ width: {BOX_PERCENT}%; height: auto; max-height: 80%; border: round $primary; background: $surface; }}
    """
    BINDINGS = [Binding("escape", "dismiss(None)", "cancel")]
    box_title = ""

    def compose(self) -> ComposeResult:
        """Lay out the list as a table with one row for each item."""
        yield DataTable(id="picker", cursor_type="row")

    def on_mount(self) -> None:
        """Show the keys on the border and fill the table."""
        table = self.query_one("#picker", DataTable)
        table.border_title = self.box_title
        self.fill_table(table)

    def fill_table(self, table: DataTable) -> None:
        """Add the columns and the rows of the list."""
        raise NotImplementedError


class SessionPicker(Picker[list[Session]]):
    """A list of recent sessions. Space selects a session, enter returns the selected sessions,
    or the highlighted session when none is selected."""

    BINDINGS = [Binding("space", "toggle", "select")]
    box_title = "Resume sessions · space selects · enter resumes · esc cancels"

    def __init__(self, listed: list[Session], palette: Palette) -> None:
        """Keep the sessions to show and the colors of the check marks."""
        super().__init__()
        self.listed = listed
        self.palette = palette
        self.checked: set[int] = set()

    def check_mark(self, row: int) -> Text:
        """Return the check mark of a row: full when the session is selected."""
        if row in self.checked:
            return Text("◉", style=f"bold {self.palette.green}")
        return Text("○", style="dim")

    def fill_table(self, table: DataTable) -> None:
        """Add one row for each session: check mark, short ID, kind, last use, folder and title."""
        text_width = text_column_width(self.app.size.width)
        table.add_columns("", "ID", "Kind", "Last used")
        table.add_column("Folder", width=text_width)
        table.add_column("Title", width=text_width)
        for row, session in enumerate(self.listed):
            table.add_row(self.check_mark(row), session.session_id[:SHORT_ID_LENGTH], session.kind,
                          f"{session.modified:%m-%d %H:%M}", cut_cell(short_path(session.cwd)), cut_cell(session.title))
        self.show_count(table)

    def show_count(self, table: DataTable) -> None:
        """Show on the border how many sessions are selected."""
        table.border_subtitle = f"{len(self.checked)} of {len(self.listed)} selected"

    def action_toggle(self) -> None:
        """Select or clear the highlighted session."""
        table = self.query_one("#picker", DataTable)
        row = table.cursor_row
        self.checked ^= {row}
        table.update_cell_at(Coordinate(row, CHECK_COLUMN), self.check_mark(row))
        self.show_count(table)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Close the list with the selected sessions, or with the highlighted one when none is selected."""
        rows = sorted(self.checked) or [event.cursor_row]
        self.dismiss([self.listed[row] for row in rows])


class LayoutPicker(Picker[Layout]):
    """A list of the named layouts. Enter returns the highlighted layout."""

    DEFAULT_CSS = "LayoutPicker #picker { width: auto; min-width: 60; }"
    box_title = "Open a layout · enter opens · esc cancels"

    def __init__(self, found: list[Layout]) -> None:
        """Keep the layouts to show."""
        super().__init__()
        self.found = found

    def fill_table(self, table: DataTable) -> None:
        """Add one row for each layout: name, time of the save, number of tabs and of agents."""
        table.add_columns("Name", "Saved", "Tabs", "Agents")
        for layout in self.found:
            table.add_row(layout.name, f"{layout.created_at:%Y-%m-%d %H:%M}",
                          Text(str(tab_count(layout.windows)), justify="right"),
                          Text(str(agent_count(layout.windows)), justify="right"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Close the list with the highlighted layout."""
        self.dismiss(self.found[event.cursor_row])

"""The restore screen: the snapshots on the left, the tabs of the selected snapshot on the right."""

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass, replace

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as RichTheme
from rich.theme import ThemeStackError
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Footer, Input, Label, ListItem, ListView, OptionList, Static
from textual.widgets.option_list import Option

from . import __version__, layouts, markdown, sessions, store
from .about import changelog_view
from .config import (
    CONFIG_FILE,
    SETTING_HELP,
    SETTING_KINDS,
    parse_setting,
    read_config,
    save_config,
    setting_text,
    settings,
    write_config,
)
from .diff import render_changes
from .display import snapshot_markup, tab_markup, tab_matches
from .history import HistoryIndex, HistoryPick, read_index
from .history_screen import HistoryScreen
from .layouts import Layout
from .logo import logo_compact
from .models import Tab, Window, positioned_tabs
from .palette import DARK, LIGHT, Palette, chosen_palette, other_palette
from .pickers import LayoutPicker, SessionPicker
from .plan import default_positions, plan_view, resolve_duplicates
from .sessions import Session

RECENT_SESSION_DAYS = 7
NO_LAYOUTS = "There are no layouts. Save one with `ai-tabs layout save NAME`."

KEYS = [
    ("↑ ↓", "move in the list"),
    ("tab", "switch between the snapshots and the tabs"),
    ("space", "select or clear the tab"),
    ("a", "select all the visible tabs, or none"),
    ("/", "search tabs, sessions and folders (esc leaves the search)"),
    ("f", "search the tabs of all the snapshots: → shows the variants, tab picks the snapshot, "
          "enter restores (esc or f leaves)"),
    ("enter", "restore the selected tabs"),
    ("r", f"resume sessions of the last {RECENT_SESSION_DAYS} days that do not run now (space selects several)"),
    ("l", "open a named layout"),
    ("c", "show the ai-tabs commands, as ai-tabs --help"),
    ("d", "dry run: show the commands that restore runs for the selected tabs"),
    ("h", "show the changes that the snapshot records"),
    ("p", "pin the snapshot, or remove its pin (pinned snapshots are never deleted)"),
    ("e", "export the snapshot as Markdown to export_dir"),
    ("o", "change the settings"),
    ("s", "take a snapshot now"),
    ("t", "switch between the dark and the light theme, and save it in the settings"),
    ("v", "show the changes of each release"),
    ("q, esc", "quit"),
]


def brand(colors: Palette) -> Text:
    """Return the small logo followed by the version, for the top bar."""
    return logo_compact(colors).append(f"  v{__version__}", style=colors.muted)


def textual_theme(colors: Palette) -> Theme:
    """Return the Textual theme of a palette.

    The cursor has its own color: the text on the plain primary color is hard to read.
    """
    return Theme(name=colors.name, primary=colors.cyan, secondary=colors.purple, accent=colors.gold,
                 warning=colors.gold, error=colors.red, success=colors.green, foreground=colors.foreground,
                 background=colors.background, surface=colors.surface, panel=colors.panel, dark=colors.dark,
                 variables={"block-cursor-background": colors.cursor, "block-cursor-foreground": colors.foreground,
                            "block-cursor-blurred-background": colors.panel})


def keys_help(colors: Palette) -> Table:
    """Return the list of keys, with the keys in the logo cyan. A long action wraps under itself."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True, style=f"bold {colors.cyan}")
    grid.add_column()
    for key, action in KEYS:
        grid.add_row(key, action)
    return grid


class SettingsScreen(ModalScreen[bool]):
    """A window to change the settings in the configuration file. An empty field means the default."""

    CSS = """
    SettingsScreen { align: center middle; }
    #settings { width: 90%; height: 85%; border: round $primary; background: $surface; padding: 0 1; }
    #settings Input { margin-bottom: 1; }
    #error { color: $error; }
    """
    BINDINGS = [Binding("escape", "dismiss(False)", "cancel"), Binding("ctrl+s", "save", "save")]

    def compose(self) -> ComposeResult:
        """Lay out one field for each setting, filled with the value of the configuration file."""
        saved = read_config()
        current = vars(settings())
        with VerticalScroll(id="settings"):
            for key in SETTING_KINDS:
                yield Label(f"[bold]{key}[/bold]  [dim]{SETTING_HELP[key]}[/dim]")
                yield Input(value=setting_text(saved.get(key, "")), placeholder=setting_text(current[key]),
                            id=f"setting-{key}")
            yield Label("", id="error")

    def on_mount(self) -> None:
        """Show how to save on the border, and the file that the window writes."""
        box = self.query_one("#settings")
        box.border_title = "Settings · ctrl+s saves · esc cancels · empty means default"
        box.border_subtitle = str(CONFIG_FILE)

    def entered_values(self) -> dict[str, object]:
        """Return the settings that the fields hold. Raise ValueError for a value that is not valid."""
        texts = {key: self.query_one(f"#setting-{key}", Input).value.strip() for key in SETTING_KINDS}
        return {key: parse_setting(key, text) for key, text in texts.items() if text}

    def action_save(self) -> None:
        """Write the settings and close the window, or show why a value is not valid."""
        try:
            values = self.entered_values()
        except ValueError as error:
            self.query_one("#error", Label).update(str(error))
            return
        save_config(values)
        self.dismiss(True)


@dataclass
class RestoreChoice:
    """What the restore screen returns: the snapshot, its selected tabs, whether to open
    them (`open_tabs`) or only print their commands, and whether they open in this window (`here`).

    When `windows` is set, the tabs come from these windows (a layout or resumed sessions)
    and not from the snapshot, and `snapshot_id` is empty."""

    snapshot_id: str
    positions: list[str]
    open_tabs: bool
    here: bool = False
    windows: list[Window] | None = None


NEW_WINDOWS, THIS_WINDOW = "new", "here"


class WhereScreen(ModalScreen[bool | None]):
    """A window that asks where the tabs open. It returns True for this window, False for new
    windows, and None when escape closes it."""

    CSS = """
    WhereScreen { align: center middle; }
    #where { width: 60; height: auto; border: round $primary; background: $surface; }
    """
    BINDINGS = [Binding("escape,q", "dismiss(None)", "cancel")]

    def compose(self) -> ComposeResult:
        """Show the two places where the tabs can open."""
        yield OptionList(Option("New windows, with the saved windows and frames", id=NEW_WINDOWS),
                         Option("New tabs in this window", id=THIS_WINDOW), id="where")

    def on_mount(self) -> None:
        """Show the question on the border."""
        self.query_one("#where").border_title = "Where do the tabs open?"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Close the window with the chosen place."""
        self.dismiss(event.option.id == THIS_WINDOW)


class InfoScreen(ModalScreen[None]):
    """A window over the restore screen with a title and a text. Escape or q closes it."""

    CSS = """
    InfoScreen { align: center middle; }
    #info { width: 90%; height: auto; max-height: 80%; border: round $primary; background: $surface; padding: 0 1; }
    """
    BINDINGS = [Binding("escape,q", "dismiss", "close")]

    def __init__(self, title: str, body: RenderableType) -> None:
        """Keep the title and the text to show."""
        super().__init__()
        self.info_title = title
        self.body = body

    def compose(self) -> ComposeResult:
        """Lay out the text in a box that scrolls."""
        with VerticalScroll(id="info"):
            yield Static(self.body)

    def on_mount(self) -> None:
        """Show the title on the border of the box."""
        self.query_one("#info").border_title = self.info_title


class RestoreApp(App[RestoreChoice]):
    """A screen to pick a snapshot and its tabs: snapshots on the left, tabs on the right."""

    TITLE = "ai-tabs"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #snapshots { width: 30; border: round $primary; text-wrap: nowrap; text-overflow: ellipsis; }
    #right { border: round $primary; }
    #tabs { height: 1fr; border: none; text-wrap: nowrap; text-overflow: ellipsis; }
    #filter { border: none; height: 1; padding: 0 1; }
    #brand { dock: top; height: 1; padding: 0 1; text-align: right; }
    ListItem { padding: 0 1 1 1; }
    """
    BINDINGS = [
        Binding("enter", "finish", "restore", priority=True),
        Binding("space", "toggle_tab", "pick"),
        Binding("r", "resume", "resume"),
        Binding("l", "layouts", "layout"),
        Binding("slash", "search", "search"),
        Binding("f", "history", "history"),
        Binding("c", "commands", "commands"),
        Binding("d", "dry_run", "dry run", show=False),
        Binding("h", "changes", "changes"),
        Binding("p", "pin", "pin"),
        Binding("question_mark", "keys", "keys"),
        Binding("s", "snapshot", "snapshot", show=False),
        Binding("e", "export", "export", show=False),
        Binding("o", "settings", "settings", show=False),
        Binding("t", "switch_theme", "theme", show=False),
        Binding("v", "changelog", "changelog", show=False),
        Binding("a", "toggle_all", "all", show=False),
        Binding("tab,shift+tab", "switch_panel", "switch panel", show=False, priority=True),
        Binding("escape", "leave", "back", show=False),
        Binding("q", "quit", "quit", show=False),
    ]

    def __init__(self, start_id: str | None, open_tabs: bool) -> None:
        """Open the screen on a snapshot, or on the recommended one when `start_id` is None.

        `open_tabs=False` (from `--dry-run`) makes Enter print the commands instead of opening the tabs.
        """
        super().__init__()
        self.summaries = store.summaries()
        self.snapshot_id = start_id or store.recommended_id() or ""
        self.open_tabs = open_tabs
        self.palette = chosen_palette()
        self.windows: list[Window] = []
        self.tabs: list[tuple[str, Tab]] = []
        self.checked: dict[str, bool] = {}
        self.history: HistoryIndex | None = None

    def compose(self) -> ComposeResult:
        """Lay out the logo bar, the snapshot list, the search field and the tab list."""
        yield Static(brand(self.palette), id="brand")
        with Horizontal():
            yield ListView(*self.snapshot_items(), id="snapshots", initial_index=self.current_index())
            with Vertical(id="right"):
                yield Input(placeholder="> press / to search tabs, sessions and folders", id="filter")
                yield OptionList(id="tabs")
        yield Footer()

    def snapshot_items(self) -> list[ListItem]:
        """Return one entry of the snapshot list for each snapshot, newest first."""
        return [ListItem(Label(Text.from_markup(snapshot_markup(summary, index == 0, self.palette))))
                for index, summary in enumerate(self.summaries)]

    def tab_prompt(self, position: str, tab: Tab, checked: bool) -> Text:
        """Return the entry of one tab in the tab list: a check mark, the tab heading and its panes.

        The blank last line separates the entries.
        """
        box = f"[bold {self.palette.green}]◉[/]" if checked else "[dim]○[/]"
        first, *rest = tab_markup(position, tab, self.palette).split("\n")
        return Text.from_markup("\n".join([f"{box} {first}", *(f"  {line}" for line in rest), ""]))

    def current_index(self) -> int:
        """Return the position of the current snapshot in the snapshot list."""
        ids = [summary.id for summary in self.summaries]
        return ids.index(self.snapshot_id) if self.snapshot_id in ids else 0

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """Turn off the keys of the restore screen while another screen is open over it."""
        return len(self.screen_stack) == 1

    def on_mount(self) -> None:
        """Use the colors of the `theme` setting, show the starting snapshot and focus its tabs."""
        self.register_theme(textual_theme(DARK))
        self.register_theme(textual_theme(LIGHT))
        self.query_one("#snapshots").border_title = "Snapshots"
        self.paint()
        if self.summaries:
            self.load_snapshot(self.summaries[self.current_index()].id)
        self.query_one("#tabs").focus()

    def paint(self) -> None:
        """Apply the current palette to the theme, the Markdown code, the logo bar and the title of the tab panel."""
        self.theme = self.palette.name
        # The default Rich style of inline code is black, which does not fit the light theme.
        with contextlib.suppress(ThemeStackError):
            self.console.pop_theme()
        self.console.push_theme(RichTheme({"markdown.code": f"bold {self.palette.cyan}"}))
        self.query_one("#brand", Static).update(brand(self.palette))
        mode = "" if self.open_tabs else " · dry run: Enter prints the commands"
        self.query_one("#right").border_title = f"Tabs   [{self.palette.green}]●[/] still runs{mode}"

    async def action_switch_theme(self) -> None:
        """Switch between the dark and the light theme, and save the choice as the `theme` setting."""
        self.palette = other_palette(self.palette)
        write_config({"theme": "dark" if self.palette.dark else "light"})
        self.paint()
        self.show_tabs()
        await self.reload_snapshot_list()

    def load_snapshot(self, wanted: str) -> None:
        """Show the tabs of a snapshot. The tabs without a running agent start selected."""
        snapshot = store.snapshot_by_id(wanted)
        self.windows = resolve_duplicates(snapshot.windows) if snapshot else []
        self.snapshot_id = wanted
        self.tabs = positioned_tabs(self.windows)
        selected = set(default_positions(self.windows))
        self.checked = {position: position in selected for position, _ in self.tabs}
        self.query_one("#tabs", OptionList).highlighted = None
        self.show_tabs()

    def show_tabs(self) -> None:
        """Fill the tab list with the tabs that match the search. The highlight stays in place."""
        query = self.query_one("#filter", Input).value
        tab_list = self.query_one("#tabs", OptionList)
        highlighted = tab_list.highlighted or 0
        tab_list.clear_options()
        tab_list.add_options([Option(self.tab_prompt(position, tab, self.checked[position]), id=position)
                              for position, tab in self.tabs if tab_matches(tab, query)])
        if tab_list.option_count:
            tab_list.highlighted = min(highlighted, tab_list.option_count - 1)
        self.query_one("#right").border_subtitle = f"{len(self.selected_positions())} of {len(self.tabs)} selected"

    def selected_positions(self) -> list[str]:
        """Return the positions of the selected tabs, in snapshot order."""
        return [position for position, _ in self.tabs if self.checked[position]]

    def visible_positions(self) -> list[str]:
        """Return the positions of the tabs that the tab list shows now."""
        tab_list = self.query_one("#tabs", OptionList)
        return [tab_list.get_option_at_index(index).id for index in range(tab_list.option_count)]

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Show the tabs of the snapshot that the snapshot list highlights."""
        index = event.list_view.index
        if index is not None and index < len(self.summaries) and self.summaries[index].id != self.snapshot_id:
            self.load_snapshot(self.summaries[index].id)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter the tab list while the search text changes."""
        self.show_tabs()

    def action_toggle_tab(self) -> None:
        """Select or clear the highlighted tab."""
        highlighted = self.query_one("#tabs", OptionList).highlighted
        if highlighted is None:
            return
        position = self.visible_positions()[highlighted]
        self.checked[position] = not self.checked[position]
        self.show_tabs()

    def action_toggle_all(self) -> None:
        """Select all the visible tabs, or clear them when all are already selected."""
        visible = self.visible_positions()
        select = not all(self.checked[position] for position in visible)
        for position in visible:
            self.checked[position] = select
        self.show_tabs()

    def action_switch_panel(self) -> None:
        """Move the focus between the snapshot list and the tab list. The search field is left out."""
        snapshots = self.query_one("#snapshots")
        (self.query_one("#tabs") if self.focused is snapshots else snapshots).focus()

    def action_search(self) -> None:
        """Move the focus to the search field."""
        self.query_one("#filter").focus()

    def action_leave(self) -> None:
        """Leave the search field, or close the screen when the focus is already on a list."""
        if self.focused is self.query_one("#filter"):
            self.query_one("#tabs").focus()
        else:
            self.exit()

    def action_commands(self) -> None:
        """Show the ai-tabs commands with their help, as `ai-tabs --help` lists them."""
        # cli imports this module, so the import waits until the window opens.
        from .cli import command_rows

        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True, style=f"bold {self.palette.cyan}")
        grid.add_column()
        for name, text in command_rows():
            grid.add_row(name, text)
        self.push_screen(InfoScreen("Commands", grid))

    def action_dry_run(self) -> None:
        """Show the commands that restore runs for the selected tabs."""
        positions = self.selected_positions()
        if not positions:
            self.notify("Select at least one tab (space).", severity="warning")
            return
        self.push_screen(InfoScreen("Dry run", plan_view(self.windows, positions)))

    def action_changes(self) -> None:
        """Show the changes that the snapshot records: opened, closed and changed panes."""
        snapshot = store.snapshot_by_id(self.snapshot_id)
        text = "\n".join(render_changes(snapshot.changes)) if snapshot else "No snapshot."
        self.push_screen(InfoScreen(f"Changes · {self.snapshot_id}", Markdown(text)))

    def action_keys(self) -> None:
        """Show all the keys of the restore screen."""
        self.push_screen(InfoScreen("Keys", Group(logo_compact(self.palette), Text(""), keys_help(self.palette))))

    def action_changelog(self) -> None:
        """Show the short view of the changelog: one line per change of each release."""
        self.push_screen(InfoScreen(f"ai-tabs v{__version__}", changelog_view(self.palette)))

    async def action_pin(self) -> None:
        """Pin the current snapshot, or remove its pin."""
        summary = next((summary for summary in self.summaries if summary.id == self.snapshot_id), None)
        if summary is None:
            return
        store.set_pin(summary.id, None if summary.pinned else "manual")
        self.notify(f"{'Removed the pin of' if summary.pinned else 'Pinned'} {summary.id}.")
        await self.reload_snapshot_list()

    def action_snapshot(self) -> None:
        """Take a snapshot now, as the launchd agent does every 5 minutes."""
        self.notify("Taking a snapshot…")
        self.snapshot_in_background()

    @work(thread=True, exclusive=True)
    def snapshot_in_background(self) -> None:
        """Run `snapshot` in a separate process, then reload the snapshot list.

        The iTerm2 API runs its own event loop, so it cannot run inside the event loop of the screen.
        """
        command = [sys.executable, "-m", "ai_tabs", "snapshot"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.call_from_thread(self.after_snapshot, (result.stdout or result.stderr).strip())

    async def after_snapshot(self, message: str) -> None:
        """Show the result of the snapshot and reload the snapshot list.

        The new snapshot makes the history index stale, so the next `f` reads the snapshots again.
        """
        self.notify(message or "Snapshot done.")
        self.history = None
        await self.reload_snapshot_list()

    async def reload_snapshot_list(self) -> None:
        """Read the snapshot list again and keep the current snapshot highlighted."""
        self.summaries = store.summaries()
        snapshot_list = self.query_one("#snapshots", ListView)
        await snapshot_list.clear()
        await snapshot_list.extend(self.snapshot_items())
        snapshot_list.index = self.current_index()

    def action_export(self) -> None:
        """Export the current snapshot as Markdown to `export_dir`."""
        snapshot = store.snapshot_by_id(self.snapshot_id)
        if snapshot is not None:
            self.notify(f"Wrote {markdown.export_snapshot(snapshot, settings().export_dir)}")

    def action_settings(self) -> None:
        """Open the settings window."""
        self.push_screen(SettingsScreen(), self.after_settings)

    def after_settings(self, saved: bool | None) -> None:
        """Confirm the save. A new database folder takes effect only at the next start."""
        if saved:
            self.notify("Saved. A new data_dir takes effect at the next start, "
                        "a new snapshot_interval after `ai-tabs install`.")

    def action_finish(self) -> None:
        """Close the screen with the selected tabs. Inside iTerm2, ask first where they open."""
        positions = self.selected_positions()
        if not positions:
            self.notify("Select at least one tab (space).", severity="warning")
            return
        self.finish_with(RestoreChoice(self.snapshot_id, positions, self.open_tabs))

    def history_index(self) -> HistoryIndex:
        """Return the index of every tab of every snapshot, and read it once when it is not in memory.

        `HistoryScreen` calls this in a worker thread, so it only reads the database.
        """
        if self.history is None:
            self.history = read_index()
        return self.history

    def action_history(self) -> None:
        """Search the tabs of all the snapshots."""
        self.push_screen(HistoryScreen(self.history_index, self.palette), self.after_history)

    def after_history(self, pick: HistoryPick | None) -> None:
        """Close the screen with the tab that the history search picked."""
        if pick is not None:
            self.finish_with(RestoreChoice(pick.snapshot_id, [pick.position], self.open_tabs))

    def action_resume(self) -> None:
        """Show the recent sessions that do not run now, to resume some of them."""
        listed = sessions.recent_sessions(RECENT_SESSION_DAYS)
        if not listed:
            self.notify(f"No session of the last {RECENT_SESSION_DAYS} days to resume.", severity="warning")
            return
        self.push_screen(SessionPicker(listed, self.palette), self.after_sessions)

    def after_sessions(self, chosen: list[Session] | None) -> None:
        """Close the screen with a window that resumes the chosen sessions."""
        if chosen:
            self.finish_with_windows([sessions.sessions_window(chosen)])

    def action_layouts(self) -> None:
        """Show the named layouts, to open one of them."""
        found = layouts.all_layouts()
        if not found:
            self.notify(NO_LAYOUTS, severity="warning")
            return
        self.push_screen(LayoutPicker(found), self.after_layout)

    def after_layout(self, layout: Layout | None) -> None:
        """Close the screen with the windows of the chosen layout."""
        if layout is not None:
            self.finish_with_windows(layout.windows)

    def finish_with_windows(self, windows: list[Window]) -> None:
        """Close the screen with all the tabs of the windows, in place of the snapshot."""
        positions = [position for position, _ in positioned_tabs(windows)]
        self.finish_with(RestoreChoice("", positions, self.open_tabs, windows=windows))

    def finish_with(self, choice: RestoreChoice) -> None:
        """Close the screen with the choice. Inside iTerm2, ask first where the tabs open."""
        if not choice.open_tabs or "ITERM_SESSION_ID" not in os.environ:
            self.exit(choice)
            return
        self.push_screen(WhereScreen(), lambda here: self.finish_in(choice, here))

    def finish_in(self, choice: RestoreChoice, here: bool | None) -> None:
        """Close the screen with the choice and the chosen place, or stay open when the question is cancelled."""
        if here is not None:
            self.exit(replace(choice, here=here))

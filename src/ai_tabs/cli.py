"""The `ai-tabs` command line."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import iterm2
import typer
from rich.table import Table

from . import backups, layouts, markdown, store
from .about import changelog_view, first_sentence, version_text
from .config import (
    CONFIG_FILE,
    LAUNCHCTL,
    LAUNCHD_LABEL,
    LAUNCHD_LOG,
    LAUNCHD_PLIST,
    SETTING_HELP,
    SETTING_KINDS,
    WATCH_LAUNCHD_LABEL,
    WATCH_LAUNCHD_PLIST,
    move_legacy_data,
    parse_setting,
    setting_source,
    setting_text,
    settings,
    unset_config,
    write_config,
)
from .display import console, print_sessions
from .doctor import has_failure, print_checks, run_checks
from .iterm import iterm_is_running, read_windows
from .models import Window, agent_count, positioned_tabs, tab_count
from .opener import open_in_current_window, open_in_new_windows
from .palette import chosen_palette
from .plan import keep_positions, print_plan, resolve_duplicates
from .screen import show_splash
from .sessions import Session, matching_sessions, print_recent_sessions, recent_sessions, sessions_window
from .snapshot import take_snapshot
from .tui import RestoreApp, RestoreChoice
from .watch import watch_iterm

HELP = """Save and restore iTerm2 tabs with their omp and Claude Code sessions.

Without a command, `ai-tabs` opens the restore screen: the snapshots on the left, the tabs
of the selected snapshot on the right.

A launchd agent takes a snapshot every 5 minutes. A second agent takes a snapshot when a tab
or window opens or closes. To set them up, run `ai-tabs install`.
The snapshots go to a SQLite database. The history keeps them for 30 days. Pinned snapshots
stay: `ai-tabs` pins the last snapshot before a reboot or a crash by itself.
"""
SNAPSHOT_HELP = "Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18)."
TAB_HELP = "Tab to restore, as WINDOW.TAB (for example 1.3). Repeat it for more tabs."
FROM_HELP = (f"{SNAPSHOT_HELP} Without it, the restore screen starts on the recommended snapshot, "
             "and `--tab` and `--all` use the latest one.")

app = typer.Typer(add_completion=False, rich_markup_mode="markdown", help=HELP)


def require_terminal(alternative: str) -> None:
    """Stop with an error when there is no terminal to ask in."""
    if not sys.stdin.isatty():
        raise typer.BadParameter(f"no terminal to ask in: use {alternative}")


def require_iterm() -> None:
    """Stop quietly when iTerm2 does not run, so that no command starts it."""
    if not iterm_is_running():
        print("iTerm2 does not run: nothing to do.", file=sys.stderr)
        raise typer.Exit()


def resolve_snapshot(reference: str) -> store.Snapshot:
    """Return the snapshot of a reference, or stop with an error."""
    snapshot = store.find_snapshot(reference)
    if snapshot is None:
        raise typer.BadParameter(f"no snapshot {reference!r}. {SNAPSHOT_HELP}")
    return snapshot


def check_positions(windows: list[Window], positions: list[str]) -> list[str]:
    """Stop with an error if a requested position does not exist in the snapshot."""
    known = {position for position, _ in positioned_tabs(windows)}
    unknown = [position for position in positions if position not in known]
    if unknown:
        message = f"unknown tab {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        raise typer.BadParameter(message, param_hint="--tab")
    return positions


def choice_windows(choice: RestoreChoice) -> list[Window]:
    """Return the windows of the choice, else the windows of its snapshot. Only the first pane of
    each agent session resumes it."""
    windows = resolve_snapshot(choice.snapshot_id).windows if choice.windows is None else choice.windows
    return resolve_duplicates(windows)


def run_choice(choice: RestoreChoice) -> None:
    """Open the selected tabs in new windows or in this window, or print their commands."""
    windows = choice_windows(choice)
    if not choice.open_tabs:
        print_plan(windows, choice.positions)
        return
    require_iterm()
    opener = open_in_current_window if choice.here else open_in_new_windows
    opener(keep_positions(windows, choice.positions))


def choice_from_options(snapshot: store.Snapshot, tabs: list[str] | None, open_tabs: bool) -> RestoreChoice:
    """Return the choice that `--tab` or `--all` gives, without the restore screen."""
    windows = snapshot.windows
    positions = check_positions(windows, tabs) if tabs else [position for position, _ in positioned_tabs(windows)]
    return RestoreChoice(snapshot.summary.id, positions, open_tabs)


def choice_from_screen(start_id: str | None, open_tabs: bool) -> RestoreChoice:
    """Ask with the restore screen, after the splash. Stop quietly when the user quits it."""
    require_terminal("--all or --tab")
    show_splash()
    choice = RestoreApp(start_id, open_tabs).run()
    if choice is None:
        raise typer.Exit()
    return choice


def print_version(value: bool) -> None:
    """Print the version and stop, when `--version` is given."""
    if value:
        print(version_text())
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    context: typer.Context,
    version: Annotated[bool, typer.Option("--version", "-V", callback=print_version, is_eager=True,
                                          help="Show the version and stop.")] = False,
) -> None:
    """Move the data from the macOS data folder to the default folder. Without a command, open the restore screen."""
    moved_from = move_legacy_data()
    if moved_from is not None:
        print(f"Moved the ai-tabs data from {moved_from} to {settings().data_dir}.", file=sys.stderr)
    if context.invoked_subcommand is None:
        run_choice(choice_from_screen(None, open_tabs=True))


@app.command()
def changelog() -> None:
    """Show the changes of each release, newest first."""
    console.print(changelog_view(chosen_palette()))


@app.command()
def snapshot() -> None:
    """Save the open tabs and agent sessions.

    For each pane, the snapshot records the tab position, title and color, the folder, and
    the omp or Claude Code session with the command that resumes it.

    The command writes a new snapshot only when the sessions changed. If iTerm2 does not run or
    has no windows, the previous snapshot stays.
    """
    require_iterm()
    iterm2.run_until_complete(take_snapshot)


@app.command()
def restore(
    tabs: Annotated[list[str] | None, typer.Option("--tab", "-t", help=TAB_HELP)] = None,
    all_tabs: Annotated[bool, typer.Option("--all", help="Restore all tabs, without the restore screen.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the commands, open nothing.")] = False,
    source: Annotated[str | None, typer.Option("--from", help=FROM_HELP)] = None,
    here: Annotated[bool, typer.Option("--here", help="With --tab or --all: open the tabs in this window.")] = False,
) -> None:
    """Open the saved tabs again and resume the agent sessions.

    The tabs open in new windows, with the saved order, title, color and window frame, or as
    new tabs of this window. Each pane runs `omp --resume` or `claude --resume` in the agent
    folder. A shell pane only goes to its folder.

    If an agent session still runs in another tab, its pane only goes to the agent folder:
    two processes on the same session file corrupt it.

    Without `--tab` or `--all`, the restore screen opens, and asks where to open the tabs.
    After a reboot or a crash, it starts on the last snapshot from before it, when nobody
    restored it yet.

    **Examples**

    * `ai-tabs restore`: pick the snapshot and the tabs on the restore screen.
    * `ai-tabs restore --from 2026-11-02/21-48-18`: open the screen on a history entry.
    * `ai-tabs restore -t 1.3 -t 1.8`: restore two tabs of the latest snapshot, without the screen.
    * `ai-tabs restore --all --here`: restore all tabs as new tabs of this window.
    * `ai-tabs restore --all --dry-run`: show the commands for all tabs, open nothing.
    """
    if tabs or all_tabs:
        choice = replace(choice_from_options(resolve_snapshot(source or store.LATEST), tabs, not dry_run), here=here)
    else:
        start_id = resolve_snapshot(source).summary.id if source else None
        choice = choice_from_screen(start_id, not dry_run)
    run_choice(choice)


@app.command()
def show(reference: Annotated[str, typer.Argument(metavar="SNAPSHOT", help=SNAPSHOT_HELP)] = store.LATEST) -> None:
    """Show the tabs and agent sessions that a snapshot holds.

    For each tab, the list shows the tab title in the tab color, then the session title and
    the folder of each pane. `●` marks the agent sessions that still run: `restore` opens
    only their folder, and does not resume them.
    """
    print_sessions(resolve_snapshot(reference), chosen_palette())


@app.command()
def history(limit: Annotated[int, typer.Option(help="Number of snapshots to show.")] = 20) -> None:
    """List the latest snapshots, newest first.

    Each snapshot shows its ID, how many tabs and agent sessions it holds, how many panes
    opened, closed or changed, and its pin. `show`, `pin` and `restore --from` accept the ID.
    """
    table = Table("ID", "Tabs", "Agents", "Opened", "Closed", "Changed", "Pinned")
    for summary in store.summaries(limit):
        pin = store.PIN_LABELS.get(summary.pinned, summary.pinned) if summary.pinned else ""
        table.add_row(summary.id, str(summary.tabs), str(summary.agents), str(summary.opened),
                      str(summary.closed), str(summary.changed), pin)
    console.print(table)


@app.command()
def pin(reference: Annotated[str, typer.Argument(metavar="SNAPSHOT", help=SNAPSHOT_HELP)]) -> None:
    """Pin a snapshot, so that the history never deletes it."""
    snapshot = resolve_snapshot(reference)
    store.set_pin(snapshot.summary.id, "manual")
    print(f"Pinned {snapshot.summary.id}.")


@app.command()
def unpin(reference: Annotated[str, typer.Argument(metavar="SNAPSHOT", help=SNAPSHOT_HELP)]) -> None:
    """Remove the pin of a snapshot. The history deletes it when it is older than `history_days`."""
    snapshot = resolve_snapshot(reference)
    store.set_pin(snapshot.summary.id, None)
    print(f"Removed the pin of {snapshot.summary.id}.")


def chosen_session(listed: list[Session], prefix: str) -> Session:
    """Return the one listed session whose ID starts with the prefix, or stop with an error."""
    found = matching_sessions(listed, prefix)
    if not found:
        raise typer.BadParameter(f"no listed session starts with {prefix!r}", param_hint="--open")
    if len(found) > 1:
        raise typer.BadParameter(f"{len(found)} listed sessions start with {prefix!r}: type more characters",
                                 param_hint="--open")
    return found[0]


OPEN_SESSION_HELP = "Resume the listed session with this ID prefix. Repeat it for more sessions."


@app.command("sessions")
def sessions_command(
    days: Annotated[int, typer.Option(help="Show the sessions with activity in the last N days.")] = 7,
    open_ids: Annotated[list[str] | None, typer.Option("--open", metavar="ID", help=OPEN_SESSION_HELP)] = None,
    here: Annotated[bool, typer.Option("--here", help="With --open: open the sessions in this window.")] = False,
) -> None:
    """List the recent omp and Claude Code sessions that do not run now, newest first.

    The last activity is the time of the last change of the session file. With `--open`, the
    selected sessions resume as tabs of one new window, or of this window with `--here`.
    """
    listed = recent_sessions(days)
    if not open_ids:
        print_recent_sessions(listed)
        return
    window = sessions_window([chosen_session(listed, prefix) for prefix in open_ids])
    require_iterm()
    opener = open_in_current_window if here else open_in_new_windows
    opener([window])



def print_backups() -> None:
    """Print the backups with date, size and snapshot count, newest first."""
    table = Table("Date", "Size", "Snapshots")
    for info in backups.list_backups():
        count = "unreadable" if info.snapshots is None else str(info.snapshots)
        table.add_row(f"{info.day}", f"{info.size / 1024:.1f} KiB", count)
    console.print(table)


def confirm_restore(path: Path) -> None:
    """Show what a restore changes and stop when the user does not agree."""
    print(f"Backup {backups.backup_day(path)} has {backups.snapshot_count(path)} snapshots. "
          f"The live database has {backups.current_count()} snapshots now.")
    if not typer.confirm("Replace the live database with this backup?"):
        print("Nothing changed.")
        raise typer.Exit(1)


def checked_backup(reference: str) -> Path:
    """Return the backup of a date or of `latest` after the integrity check. Stop with an error when it fails."""
    try:
        path = backups.find_backup(reference)
        backups.check_backup(path)
    except backups.BackupError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error
    return path


def restore_from_backup(path: Path) -> None:
    """Restore a checked backup into the live database and print where the safety copy is."""
    result = backups.restore_backup(path, datetime.now())
    print(f"Safety copy of the old database: {result.safety_copy}")
    print("The daily prune does not delete the safety copy. Delete it yourself when you do not need it.")
    print(f"Restored {result.snapshots} snapshots from {path}")


@app.command()
def backup(
    list_all: Annotated[bool, typer.Option("--list", help="List the backups and do not write one.")] = False,
    restore_day: Annotated[str | None, typer.Option(
        "--restore", metavar="DATE", help="Restore the backup of DATE (YYYY-MM-DD) or `latest`.")] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Restore without a question.")] = False,
) -> None:
    """Write a backup of the snapshot database now, list the backups, or restore one.

    `snapshot` also writes the backup of the day by itself, at its first run at or after each time of
    `backup_times`. When the data did not change since the newest backup, that backup only gets the
    name and the time of now. The backups go to `backup_dir` and only the newest `backup_keep`
    stay. `--restore` first writes a safety copy of the live database.
    """
    if list_all:
        print_backups()
    elif restore_day:
        path = checked_backup(restore_day)
        if not yes:
            confirm_restore(path)
        restore_from_backup(path)
    else:
        print(f"Wrote {store.write_backup(date.today())}")


@app.command()
def export(
    references: Annotated[list[str] | None, typer.Argument(metavar="SNAPSHOT...", help=SNAPSHOT_HELP)] = None,
    to: Annotated[Path | None, typer.Option("--to", help="Folder of the Markdown files. Default: export_dir.")] = None,
) -> None:
    """Write snapshots as Markdown files, one file per snapshot: `FOLDER/YYYY-MM-DD/HH-MM-SS.md`.

    Without a snapshot, the command exports `latest`. Each file has a front matter for Obsidian
    properties, the changes, a table of the panes and the resume commands.
    """
    target = to.expanduser() if to else settings().export_dir
    for reference in references or [store.LATEST]:
        print(f"Wrote {markdown.export_snapshot(resolve_snapshot(reference), target)}")


def tool_command(subcommand: str) -> list[str]:
    """Return the command that launchd runs for an `ai-tabs` subcommand.

    A tool installed with `uv tool install` has a stable path. Without it, launchd runs the
    package through `uvx`.
    """
    installed = shutil.which("ai-tabs")
    if installed and "/.cache/" not in installed:
        return [installed, subcommand]
    return [shutil.which("uvx") or "/opt/homebrew/bin/uvx", "ai-tabs", subcommand]


@dataclass(frozen=True)
class LaunchAgent:
    """A launchd agent of ai-tabs. `schedule` holds the plist keys that tell launchd when to run the command."""

    label: str
    plist: Path
    command: list[str]
    schedule: str


def snapshot_agent() -> LaunchAgent:
    """Return the agent that takes a snapshot at login and every `snapshot_interval` seconds."""
    schedule = f"""  <key>StartInterval</key>
  <integer>{settings().snapshot_interval}</integer>"""
    return LaunchAgent(LAUNCHD_LABEL, LAUNCHD_PLIST, tool_command("snapshot"), schedule)


def watch_agent() -> LaunchAgent:
    """Return the agent that runs `ai-tabs watch`. launchd starts it again, at most every 30 seconds, when it stops."""
    schedule = """  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>"""
    return LaunchAgent(WATCH_LAUNCHD_LABEL, WATCH_LAUNCHD_PLIST, tool_command("watch"), schedule)


def launchd_plist(agent: LaunchAgent) -> str:
    """Return the plist of a launchd agent: it starts at load, with a fixed PATH and the ai-tabs log."""
    items = "".join(f"\n    <string>{argument}</string>" for argument in agent.command)
    path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{agent.label}</string>
  <key>ProgramArguments</key>
  <array>{items}
  </array>
{agent.schedule}
  <key>RunAtLoad</key>
  <true/>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{path}</string>
  </dict>
  <key>StandardOutPath</key>
  <string>{LAUNCHD_LOG}</string>
  <key>StandardErrorPath</key>
  <string>{LAUNCHD_LOG}</string>
</dict>
</plist>
"""


def unload_agent(agent: LaunchAgent) -> None:
    """Stop a launchd agent. It is not an error when the agent is not loaded."""
    subprocess.run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{agent.label}"], capture_output=True, check=False)


def load_agent(agent: LaunchAgent) -> None:
    """Write the plist of a launchd agent and load it again."""
    agent.plist.parent.mkdir(parents=True, exist_ok=True)
    agent.plist.write_text(launchd_plist(agent))
    unload_agent(agent)
    subprocess.run([LAUNCHCTL, "bootstrap", f"gui/{os.getuid()}", str(agent.plist)], check=True)
    print(f"Loaded {agent.plist}.")


def remove_agent(agent: LaunchAgent) -> None:
    """Stop a launchd agent and delete its plist."""
    unload_agent(agent)
    if agent.plist.exists():
        agent.plist.unlink()
        print(f"Removed {agent.plist}.")


@app.command()
def install() -> None:
    """Load the launchd agents that take the snapshots.

    One agent runs `ai-tabs snapshot` at login and every `snapshot_interval` seconds. It finds the
    agent sessions that start in a pane that is already open. When `watch` is true, a second agent
    runs `ai-tabs watch`, which takes a snapshot when a tab or window opens or closes. The log is
    `~/Library/Logs/ai-tabs.log`. Run the command again after you move or reinstall the tool,
    or after you change `snapshot_interval` or `watch`.
    """
    load_agent(snapshot_agent())
    if settings().watch:
        load_agent(watch_agent())
    else:
        remove_agent(watch_agent())
    print(f"The database is {settings().database}.")


@app.command()
def uninstall() -> None:
    """Stop and remove the launchd agents. The database, the backups and the configuration stay."""
    remove_agent(snapshot_agent())
    remove_agent(watch_agent())
    print(f"The data stays in {settings().data_dir}.")


@app.command()
def watch() -> None:
    """Take a snapshot when a tab, a window or a pane opens or closes.

    The command runs until you stop it. A burst of changes gives one snapshot, 2 seconds after the
    last change. When iTerm2 does not run, the command waits and connects again when iTerm2 starts.
    `ai-tabs install` loads it as a launchd agent when the `watch` setting is true.
    """
    watch_iterm()


@app.command()
def doctor() -> None:
    """Check iTerm2, its Python API, the launchd agents, the database, the backups and the agent detection.

    Each row shows `ok`, `warn` or `fail`, the check and what it found. The command only reads.
    The exit code is 1 when a check fails, else 0.
    """
    checks = run_checks(tool_command("snapshot")[0])
    print_checks(checks, chosen_palette())
    if has_failure(checks):
        raise typer.Exit(1)



CONFIG_HELP = "Show or change the settings in `$XDG_CONFIG_HOME/ai-tabs/config.toml` (default `~/.config/ai-tabs`)."
config_app = typer.Typer(rich_markup_mode="markdown", help=CONFIG_HELP)
app.add_typer(config_app, name="config")


@config_app.callback(invoke_without_command=True)
def config_show(context: typer.Context) -> None:
    """Without a subcommand, show every setting, its value and where the value comes from."""
    if context.invoked_subcommand is not None:
        return
    current = vars(settings())
    table = Table("Setting", "Value", "Source", "Meaning", title=str(CONFIG_FILE))
    for key in SETTING_KINDS:
        table.add_row(key, setting_text(current[key]), setting_source(key), SETTING_HELP[key])
    console.print(table)


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help=f"One of: {', '.join(SETTING_KINDS)}.")],
    value: Annotated[str, typer.Argument(
        help="A folder, true or false, a whole number, or times such as 09:00,17:00, as the setting needs.")],
) -> None:
    """Set a setting in the configuration file. A folder becomes an absolute path."""
    try:
        parsed = parse_setting(key, value)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    write_config({key: parsed})
    print(f"{key} = {setting_text(parsed)}")


@config_app.command("unset")
def config_unset(key: Annotated[str, typer.Argument(help=f"One of: {', '.join(SETTING_KINDS)}.")]) -> None:
    """Remove a setting from the configuration file, so that it takes its default again."""
    if key not in SETTING_KINDS:
        raise typer.BadParameter(f"unknown setting {key!r}; the settings are {', '.join(SETTING_KINDS)}")
    unset_config(key)
    print(f"{key} = {setting_text(getattr(settings(), key))} (default)")


LAYOUT_HELP = """Save tabs under a name, and open them again later.

A layout stays until you delete it: the history prune never deletes a layout.
"""
LAYOUT_NAME_HELP = f"Layout name: {layouts.NAME_RULE}."
LAYOUT_FROM_HELP = f"{SNAPSHOT_HELP} Without it, the layout takes the windows that iTerm2 shows now."
LAYOUT_TAB_HELP = "Tab to keep in the layout, as WINDOW.TAB (for example 1.3). Repeat it for more tabs."
layout_app = typer.Typer(rich_markup_mode="markdown", help=LAYOUT_HELP)
app.add_typer(layout_app, name="layout")


def valid_layout_name(name: str) -> str:
    """Stop with an error that tells why, when a layout name is not valid."""
    problem = layouts.name_problem(name)
    if problem is not None:
        raise typer.BadParameter(problem)
    return name


def resolve_layout(name: str) -> layouts.Layout:
    """Return the layout with a name, or stop with an error that lists the known names."""
    layout = layouts.find_layout(name)
    if layout is None:
        known = ", ".join(layouts.layout_names()) or "none"
        raise typer.BadParameter(f"no layout {name!r}; known layouts: {known}", param_hint="NAME")
    return layout


def current_windows() -> list[Window]:
    """Read the windows, tabs and panes that iTerm2 shows now. Stop quietly when iTerm2 does not run."""
    require_iterm()
    return iterm2.run_until_complete(read_windows)


def layout_source(source: str | None, tabs: list[str] | None) -> list[Window]:
    """Return the windows of a snapshot, or of iTerm2 now, with only the requested tabs."""
    windows = resolve_snapshot(source).windows if source else current_windows()
    return keep_positions(windows, check_positions(windows, tabs)) if tabs else windows


def all_positions(windows: list[Window]) -> list[str]:
    """Return the position of every tab."""
    return [position for position, _ in positioned_tabs(windows)]


@layout_app.command("save")
def layout_save(
    name: Annotated[str, typer.Argument(metavar="NAME", callback=valid_layout_name, help=LAYOUT_NAME_HELP)],
    source: Annotated[str | None, typer.Option("--from", help=LAYOUT_FROM_HELP)] = None,
    tabs: Annotated[list[str] | None, typer.Option("--tab", "-t", help=LAYOUT_TAB_HELP)] = None,
) -> None:
    """Save tabs as a layout. A layout with the same name gets replaced.

    **Examples**

    * `ai-tabs layout save work`: save all the tabs that iTerm2 shows now.
    * `ai-tabs layout save work --from latest -t 1.3 -t 1.8`: save two tabs of the latest snapshot.
    """
    windows = layout_source(source, tabs)
    if not windows:
        raise typer.BadParameter("there are no tabs to save", param_hint="NAME")
    replaced = layouts.save_layout(name, windows, datetime.now())
    action = "Replaced" if replaced else "Saved"
    print(f"{action} layout {name}: {tab_count(windows)} tabs, {agent_count(windows)} agents.")


@layout_app.command("list")
def layout_list() -> None:
    """List the layouts with the time when they were saved and their number of tabs and agents."""
    table = Table("Name", "Saved", "Tabs", "Agents")
    for layout in layouts.all_layouts():
        table.add_row(layout.name, f"{layout.created_at:%Y-%m-%d %H:%M:%S}", str(tab_count(layout.windows)),
                      str(agent_count(layout.windows)))
    console.print(table)


@layout_app.command("show")
def layout_show(name: Annotated[str, typer.Argument(metavar="NAME", help=LAYOUT_NAME_HELP)]) -> None:
    """Show the commands that `layout open` runs, as `restore --dry-run` does."""
    windows = resolve_duplicates(resolve_layout(name).windows)
    print_plan(windows, all_positions(windows))


@layout_app.command("open")
def layout_open(
    name: Annotated[str, typer.Argument(metavar="NAME", help=LAYOUT_NAME_HELP)],
    here: Annotated[bool, typer.Option("--here", help="Open the tabs in this window.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the commands, open nothing.")] = False,
) -> None:
    """Open the tabs of a layout and resume their agent sessions.

    The tabs open in new windows, or as new tabs of this window with `--here`. If an agent
    session still runs in another tab, its pane only goes to the agent folder.
    """
    windows = resolve_duplicates(resolve_layout(name).windows)
    if dry_run:
        print_plan(windows, all_positions(windows))
        return
    require_iterm()
    opener = open_in_current_window if here else open_in_new_windows
    opener(windows)


@layout_app.command("delete")
def layout_delete(name: Annotated[str, typer.Argument(metavar="NAME", help=LAYOUT_NAME_HELP)]) -> None:
    """Delete a layout."""
    resolve_layout(name)
    layouts.delete_layout(name)
    print(f"Deleted layout {name}.")



def short_help(text: str | None) -> str:
    """Return the first sentence of a help text on one line, as the command list of `ai-tabs --help` shows it."""
    paragraph = (text or "").strip().split("\n\n")[0]
    return first_sentence(" ".join(paragraph.split()))


def command_rows() -> list[tuple[str, str]]:
    """Return each command of `ai-tabs` with the first sentence of its help, in the order of `ai-tabs --help`.
    A group comes first, then each of its subcommands."""
    rows = [("ai-tabs", "Open the restore screen.")]
    for name, command in typer.main.get_command(app).commands.items():
        rows.append((f"ai-tabs {name}", short_help(command.help)))
        subcommands = getattr(command, "commands", {})
        rows += [(f"ai-tabs {name} {sub}", short_help(item.help)) for sub, item in subcommands.items()]
    return rows


def run() -> None:
    """Run the command line, with the program name that the help shows."""
    app(prog_name="ai-tabs")

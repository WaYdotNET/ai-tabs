"""The `ai-tabs` command line."""

import os
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Annotated

import iterm2
import typer
from rich.table import Table

from . import markdown, store
from .config import (
    CONFIG_FILE,
    LAUNCHCTL,
    LAUNCHD_LABEL,
    LAUNCHD_LOG,
    LAUNCHD_PLIST,
    SETTING_HELP,
    SETTING_KINDS,
    parse_setting,
    setting_source,
    setting_text,
    settings,
    unset_config,
    write_config,
)
from .display import console, print_sessions
from .iterm import iterm_is_running
from .models import Window, positioned_tabs
from .opener import open_in_current_window, open_in_new_windows
from .palette import chosen_palette
from .plan import keep_positions, print_plan, resolve_duplicates
from .screen import show_splash
from .snapshot import take_snapshot
from .tui import RestoreApp, RestoreChoice

HELP = """Save and restore iTerm2 tabs with their omp and Claude Code sessions.

Without a command, `ai-tabs` opens the restore screen: the snapshots on the left, the tabs
of the selected snapshot on the right.

A launchd agent takes a snapshot every 5 minutes. To set it up, run `ai-tabs install`.
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


def run_choice(choice: RestoreChoice) -> None:
    """Open the selected tabs in new windows or in this window, or print their commands."""
    windows = resolve_duplicates(resolve_snapshot(choice.snapshot_id).windows)
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


@app.callback(invoke_without_command=True)
def main(context: typer.Context) -> None:
    """Without a command, open the restore screen."""
    if context.invoked_subcommand is None:
        run_choice(choice_from_screen(None, open_tabs=True))


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


@app.command()
def backup() -> None:
    """Write a backup of the snapshot database now.

    `snapshot` also writes one backup a day by itself. The backups go to `backup_dir` and only
    the newest `backup_keep` stay. To use a backup, copy it over the database file.
    """
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


def snapshot_command() -> list[str]:
    """Return the command that launchd runs to take a snapshot.

    A tool installed with `uv tool install` has a stable path. Without it, launchd runs the
    package through `uvx`.
    """
    installed = shutil.which("ai-tabs")
    if installed and "/.cache/" not in installed:
        return [installed, "snapshot"]
    return [shutil.which("uvx") or "/opt/homebrew/bin/uvx", "ai-tabs", "snapshot"]


def launchd_plist(command: list[str]) -> str:
    """Return the launchd agent that takes a snapshot every few minutes."""
    items = "".join(f"\n    <string>{argument}</string>" for argument in command)
    path = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>{items}
  </array>
  <key>StartInterval</key>
  <integer>{settings().snapshot_interval}</integer>
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


def unload_agent() -> None:
    """Stop the launchd agent. It is not an error when the agent is not loaded."""
    subprocess.run([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], capture_output=True, check=False)


@app.command()
def install() -> None:
    """Load the launchd agent that takes the snapshots.

    The agent runs `ai-tabs snapshot` at login and every `snapshot_interval` seconds. Its log is
    `~/Library/Logs/ai-tabs.log`. Run the command again after you move or reinstall the tool,
    or after you change `snapshot_interval`.
    """
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST.write_text(launchd_plist(snapshot_command()))
    unload_agent()
    subprocess.run([LAUNCHCTL, "bootstrap", f"gui/{os.getuid()}", str(LAUNCHD_PLIST)], check=True)
    print(f"Loaded {LAUNCHD_PLIST}. The database is {settings().database}.")


@app.command()
def uninstall() -> None:
    """Stop and remove the launchd agent. The database, the backups and the configuration stay."""
    unload_agent()
    LAUNCHD_PLIST.unlink(missing_ok=True)
    print(f"Removed {LAUNCHD_PLIST}. The data stays in {settings().data_dir}.")


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
    value: Annotated[str, typer.Argument(help="A folder, true or false, or a whole number, as the setting needs.")],
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


def run() -> None:
    """Run the command line, with the program name that the help shows."""
    app(prog_name="ai-tabs")

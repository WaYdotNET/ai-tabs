# ai-tabs

Save and restore iTerm2 tabs with their omp and Claude Code sessions.

Without a command, `ai-tabs` opens the restore screen: the snapshots on the left, the tabs
of the selected snapshot on the right.

A launchd agent takes a snapshot every 5 minutes. A second agent takes a snapshot when a tab
or window opens or closes. To set them up, run `ai-tabs install`.
The snapshots go to a SQLite database. The history keeps them for 30 days. Pinned snapshots
stay: `ai-tabs` pins the last snapshot before a reboot or a crash by itself.

**Usage**:

```console
$ ai-tabs [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `-V, --version`: Show the version and stop.
* `--help`: Show this message and exit.

**Commands**:

* `changelog`: Show the changes of each release, newest...
* `snapshot`: Save the open tabs and agent sessions.
* `restore`: Open the saved tabs again and resume the...
* `show`: Show the tabs and agent sessions that a...
* `history`: List the latest snapshots, newest first.
* `pin`: Pin a snapshot, so that the history never...
* `unpin`: Remove the pin of a snapshot.
* `sessions`: List the recent omp and Claude Code...
* `backup`: Write a backup of the snapshot database...
* `export`: Write snapshots as Markdown files, one...
* `install`: Load the launchd agents that take the...
* `uninstall`: Stop and remove the launchd agents.
* `watch`: Take a snapshot when a tab, a window or a...
* `doctor`: Check iTerm2, its Python API, the launchd...
* `config`: Show or change the settings in...
* `layout`: Save tabs under a name, and open them...

## `ai-tabs changelog`

Show the changes of each release, newest first.

**Usage**:

```console
$ ai-tabs changelog [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs snapshot`

Save the open tabs and agent sessions.

For each pane, the snapshot records the tab position, title and color, the folder, and
the omp or Claude Code session with the command that resumes it.

The command writes a new snapshot only when the sessions changed. If iTerm2 does not run or
has no windows, the previous snapshot stays.

**Usage**:

```console
$ ai-tabs snapshot [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs restore`

Open the saved tabs again and resume the agent sessions.

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

**Usage**:

```console
$ ai-tabs restore [OPTIONS]
```

**Options**:

* `-t, --tab <str>`: Tab to restore, as WINDOW.TAB (for example 1.3). Repeat it for more tabs.
* `--all`: Restore all tabs, without the restore screen.
* `--dry-run`: Show the commands, open nothing.
* `--from <str>`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18). Without it, the restore screen starts on the recommended snapshot, and `--tab` and `--all` use the latest one.
* `--here`: With --tab or --all: open the tabs in this window.
* `--help`: Show this message and exit.

## `ai-tabs show`

Show the tabs and agent sessions that a snapshot holds.

For each tab, the list shows the tab title in the tab color, then the session title and
the folder of each pane. `●` marks the agent sessions that still run: `restore` opens
only their folder, and does not resume them.

**Usage**:

```console
$ ai-tabs show [OPTIONS] [SNAPSHOT]
```

**Arguments**:

* `SNAPSHOT`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18).  [default: latest]

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs history`

List the latest snapshots, newest first.

Each snapshot shows its ID, how many tabs and agent sessions it holds, how many panes
opened, closed or changed, and its pin. `show`, `pin` and `restore --from` accept the ID.

**Usage**:

```console
$ ai-tabs history [OPTIONS]
```

**Options**:

* `--limit <int>`: Number of snapshots to show.  [default: 20]
* `--help`: Show this message and exit.

## `ai-tabs pin`

Pin a snapshot, so that the history never deletes it.

**Usage**:

```console
$ ai-tabs pin [OPTIONS] {SNAPSHOT}
```

**Arguments**:

* `SNAPSHOT`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18).  [required]

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs unpin`

Remove the pin of a snapshot. The history deletes it when it is older than `history_days`.

**Usage**:

```console
$ ai-tabs unpin [OPTIONS] {SNAPSHOT}
```

**Arguments**:

* `SNAPSHOT`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18).  [required]

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs sessions`

List the recent omp and Claude Code sessions that do not run now, newest first.

The last activity is the time of the last change of the session file. With `--open`, the
selected sessions resume as tabs of one new window, or of this window with `--here`.

**Usage**:

```console
$ ai-tabs sessions [OPTIONS]
```

**Options**:

* `--days <int>`: Show the sessions with activity in the last N days.  [default: 7]
* `--open ID`: Resume the listed session with this ID prefix. Repeat it for more sessions.
* `--here`: With --open: open the sessions in this window.
* `--help`: Show this message and exit.

## `ai-tabs backup`

Write a backup of the snapshot database now, list the backups, or restore one.

`snapshot` also writes the backup of the day by itself, at its first run at or after each time of
`backup_times`. When the data did not change since the newest backup, that backup only gets the
name and the time of now. The backups go to `backup_dir` and only the newest `backup_keep`
stay. `--restore` first writes a safety copy of the live database.

**Usage**:

```console
$ ai-tabs backup [OPTIONS]
```

**Options**:

* `--list`: List the backups and do not write one.
* `--restore DATE`: Restore the backup of DATE (YYYY-MM-DD) or `latest`.
* `--yes`: Restore without a question.
* `--help`: Show this message and exit.

## `ai-tabs export`

Write snapshots as Markdown files, one file per snapshot: `FOLDER/YYYY-MM-DD/HH-MM-SS.md`.

Without a snapshot, the command exports `latest`. Each file has a front matter for Obsidian
properties, the changes, a table of the panes and the resume commands.

**Usage**:

```console
$ ai-tabs export [OPTIONS] [SNAPSHOT...]
```

**Arguments**:

* `SNAPSHOT...`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18).

**Options**:

* `--to <path>`: Folder of the Markdown files. Default: export_dir.
* `--help`: Show this message and exit.

## `ai-tabs install`

Load the launchd agents that take the snapshots.

One agent runs `ai-tabs snapshot` at login and every `snapshot_interval` seconds. It finds the
agent sessions that start in a pane that is already open. When `watch` is true, a second agent
runs `ai-tabs watch`, which takes a snapshot when a tab or window opens or closes. The log is
`~/Library/Logs/ai-tabs.log`. Run the command again after you move or reinstall the tool,
or after you change `snapshot_interval` or `watch`.

**Usage**:

```console
$ ai-tabs install [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs uninstall`

Stop and remove the launchd agents. The database, the backups and the configuration stay.

**Usage**:

```console
$ ai-tabs uninstall [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs watch`

Take a snapshot when a tab, a window or a pane opens or closes.

The command runs until you stop it. A burst of changes gives one snapshot, 2 seconds after the
last change. When iTerm2 does not run, the command waits and connects again when iTerm2 starts.
`ai-tabs install` loads it as a launchd agent when the `watch` setting is true.

**Usage**:

```console
$ ai-tabs watch [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs doctor`

Check iTerm2, its Python API, the launchd agents, the database, the backups and the agent detection.

Each row shows `ok`, `warn` or `fail`, the check and what it found. The command only reads.
The exit code is 1 when a check fails, else 0.

**Usage**:

```console
$ ai-tabs doctor [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs config`

Show or change the settings in `$XDG_CONFIG_HOME/ai-tabs/config.toml` (default `~/.config/ai-tabs`).

**Usage**:

```console
$ ai-tabs config [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `set`: Set a setting in the configuration file.
* `unset`: Remove a setting from the configuration...

### `ai-tabs config set`

Set a setting in the configuration file. A folder becomes an absolute path.

**Usage**:

```console
$ ai-tabs config set [OPTIONS] {key} {value}
```

**Arguments**:

* `key`: One of: data_dir, export_dir, export_latest, backup_dir, backup_keep, backup_times, history_days, snapshot_interval, splash, theme, watch.  [required]
* `value`: A folder, true or false, a whole number, or times such as 09:00,17:00, as the setting needs.  [required]

**Options**:

* `--help`: Show this message and exit.

### `ai-tabs config unset`

Remove a setting from the configuration file, so that it takes its default again.

**Usage**:

```console
$ ai-tabs config unset [OPTIONS] {key}
```

**Arguments**:

* `key`: One of: data_dir, export_dir, export_latest, backup_dir, backup_keep, backup_times, history_days, snapshot_interval, splash, theme, watch.  [required]

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs layout`

Save tabs under a name, and open them again later.

A layout stays until you delete it: the history prune never deletes a layout.

**Usage**:

```console
$ ai-tabs layout [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `save`: Save tabs as a layout.
* `list`: List the layouts with the time when they...
* `show`: Show the commands that `layout open` runs,...
* `open`: Open the tabs of a layout and resume their...
* `delete`: Delete a layout.

### `ai-tabs layout save`

Save tabs as a layout. A layout with the same name gets replaced.

**Examples**

* `ai-tabs layout save work`: save all the tabs that iTerm2 shows now.
* `ai-tabs layout save work --from latest -t 1.3 -t 1.8`: save two tabs of the latest snapshot.

**Usage**:

```console
$ ai-tabs layout save [OPTIONS] {NAME}
```

**Arguments**:

* `NAME`: Layout name: 1 to 40 characters: letters, digits, '-', '_' and '.'.  [required]

**Options**:

* `--from <str>`: Snapshot: `latest` or an ID from `ai-tabs history` (for example 2026-11-02/21-48-18). Without it, the layout takes the windows that iTerm2 shows now.
* `-t, --tab <str>`: Tab to keep in the layout, as WINDOW.TAB (for example 1.3). Repeat it for more tabs.
* `--help`: Show this message and exit.

### `ai-tabs layout list`

List the layouts with the time when they were saved and their number of tabs and agents.

**Usage**:

```console
$ ai-tabs layout list [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

### `ai-tabs layout show`

Show the commands that `layout open` runs, as `restore --dry-run` does.

**Usage**:

```console
$ ai-tabs layout show [OPTIONS] {NAME}
```

**Arguments**:

* `NAME`: Layout name: 1 to 40 characters: letters, digits, '-', '_' and '.'.  [required]

**Options**:

* `--help`: Show this message and exit.

### `ai-tabs layout open`

Open the tabs of a layout and resume their agent sessions.

The tabs open in new windows, or as new tabs of this window with `--here`. If an agent
session still runs in another tab, its pane only goes to the agent folder.

**Usage**:

```console
$ ai-tabs layout open [OPTIONS] {NAME}
```

**Arguments**:

* `NAME`: Layout name: 1 to 40 characters: letters, digits, '-', '_' and '.'.  [required]

**Options**:

* `--here`: Open the tabs in this window.
* `--dry-run`: Show the commands, open nothing.
* `--help`: Show this message and exit.

### `ai-tabs layout delete`

Delete a layout.

**Usage**:

```console
$ ai-tabs layout delete [OPTIONS] {NAME}
```

**Arguments**:

* `NAME`: Layout name: 1 to 40 characters: letters, digits, '-', '_' and '.'.  [required]

**Options**:

* `--help`: Show this message and exit.

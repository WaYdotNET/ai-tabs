# ai-tabs

Save and restore iTerm2 tabs with their omp and Claude Code sessions.

Without a command, `ai-tabs` opens the restore screen: the snapshots on the left, the tabs
of the selected snapshot on the right.

A launchd agent takes a snapshot every 5 minutes. To set it up, run `ai-tabs install`.
The snapshots go to a SQLite database. The history keeps them for 30 days. Pinned snapshots
stay: `ai-tabs` pins the last snapshot before a reboot or a crash by itself.

**Usage**:

```console
$ ai-tabs [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `snapshot`: Save the open tabs and agent sessions.
* `restore`: Open the saved tabs again and resume the...
* `show`: Show the tabs and agent sessions that a...
* `history`: List the latest snapshots, newest first.
* `pin`: Pin a snapshot, so that the history never...
* `unpin`: Remove the pin of a snapshot.
* `backup`: Write a backup of the snapshot database now.
* `export`: Write snapshots as Markdown files, one...
* `install`: Load the launchd agent that takes the...
* `uninstall`: Stop and remove the launchd agent.
* `config`: Show or change the settings in...

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

The tabs open in new windows, with the saved order, title, color and window frame. Each
pane runs `omp --resume` or `claude --resume` in the agent folder. A shell pane only goes
to its folder.

If an agent session still runs in another tab, its pane only goes to the agent folder:
two processes on the same session file corrupt it.

Without `--tab` or `--all`, the restore screen opens. After a reboot or a crash, it starts
on the last snapshot from before it, when nobody restored it yet.

**Examples**

* `ai-tabs restore`: pick the snapshot and the tabs on the restore screen.
* `ai-tabs restore --from 2026-11-02/21-48-18`: open the screen on a history entry.
* `ai-tabs restore -t 1.3 -t 1.8`: restore two tabs of the latest snapshot, without the screen.
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

## `ai-tabs backup`

Write a backup of the snapshot database now.

`snapshot` also writes one backup a day by itself. The backups go to `backup_dir` and only
the newest `backup_keep` stay. To use a backup, copy it over the database file.

**Usage**:

```console
$ ai-tabs backup [OPTIONS]
```

**Options**:

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

Load the launchd agent that takes the snapshots.

The agent runs `ai-tabs snapshot` at login and every `snapshot_interval` seconds. Its log is
`~/Library/Logs/ai-tabs.log`. Run the command again after you move or reinstall the tool,
or after you change `snapshot_interval`.

**Usage**:

```console
$ ai-tabs install [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `ai-tabs uninstall`

Stop and remove the launchd agent. The database, the backups and the configuration stay.

**Usage**:

```console
$ ai-tabs uninstall [OPTIONS]
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

* `key`: One of: data_dir, export_dir, export_latest, backup_dir, backup_keep, history_days, snapshot_interval, splash, tui_font_size.  [required]
* `value`: A folder, true or false, or a whole number, as the setting needs.  [required]

**Options**:

* `--help`: Show this message and exit.

### `ai-tabs config unset`

Remove a setting from the configuration file, so that it takes its default again.

**Usage**:

```console
$ ai-tabs config unset [OPTIONS] {key}
```

**Arguments**:

* `key`: One of: data_dir, export_dir, export_latest, backup_dir, backup_keep, history_days, snapshot_interval, splash, tui_font_size.  [required]

**Options**:

* `--help`: Show this message and exit.

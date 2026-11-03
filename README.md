<p align="center"><img src="https://raw.githubusercontent.com/WaYdotNET/ai-tabs/main/src/ai_tabs/assets/logo.png" alt="ai-tabs" width="360"></p>

# ai-tabs

`ai-tabs` saves your iTerm2 tabs, and the omp and Claude Code sessions in them. After a reboot or a crash, it opens the tabs again and resumes each agent session.

- It takes a snapshot every 5 minutes through the iTerm2 Python API. A snapshot holds the windows, the tab order, titles and colors, the split layout, the iTerm2 profile of each pane, and the agent session in each pane.
- It keeps the snapshots in a SQLite database for 30 days. It pins the last snapshot before a reboot, or before many tabs close at once. The history never deletes pinned snapshots.
- A terminal screen lets you pick a snapshot and the tabs to open again.
- It can also export the snapshots as Markdown files, for example into an Obsidian vault.

## Requirements

- macOS with [iTerm2](https://iterm2.com) 3.5 or later.
- The iTerm2 Python API: open **iTerm2 › Settings › General › Magic** and select **Enable Python API**.
- [uv](https://docs.astral.sh/uv/). uv installs Python 3.15 for `ai-tabs` when it is necessary.
- Optional: [iTerm2 shell integration](https://iterm2.com/documentation-shell-integration.html). With it, `ai-tabs` waits for the shell prompt before it types the resume command.

## Install

To run the tool without an install:

```sh
uvx ai-tabs
```

To install it, so that the launchd agent has a stable path:

```sh
uv tool install ai-tabs
```

To install the latest `main` branch from GitHub:

```sh
uv tool install git+https://github.com/WaYdotNET/ai-tabs
```

Then start the snapshots. This command loads a launchd agent that runs `ai-tabs snapshot` at login and every `snapshot_interval` seconds (default 300):

```sh
ai-tabs install
```

To stop the snapshots, run `ai-tabs uninstall`. The database, the backups and the configuration stay.

## Use

Run `ai-tabs` without a command to open the restore screen. In iTerm2, the logo shows for a moment first (setting `splash`):

- The screen uses the colors of the logo, in a dark and a light theme. The `theme` setting chooses one, and `auto` (the default) follows the macOS appearance. Press `t` to switch: it saves the choice as `theme = "dark"` or `theme = "light"` in the configuration file. The top bar shows the small logo. Press `?` for the list of all the keys.
- The left panel shows the snapshots, newest first. 📌 marks a pinned snapshot. A gold line shows how many panes opened and closed.
- The right panel shows the tabs of the selected snapshot. A bar in the tab color comes first, then the tab title, the session title and the folder. A green `●` marks an agent session that still runs.
- After a reboot or a crash, the screen starts on the last snapshot from before it, until you restore it.

| Key | Action |
|---|---|
| `↑` `↓` | Move in the list |
| `tab` | Switch between the snapshots and the tabs |
| `space` | Select or clear a tab |
| `a` | Select all the visible tabs, or none |
| `/` | Search tabs, sessions and folders. `esc` leaves the search |
| `enter` | Restore the selected tabs. In iTerm2, it asks first: new windows, or new tabs in this window |
| `c` | Show the commands that restore runs |
| `h` | Show the changes that the snapshot records |
| `p` | Pin the snapshot, or remove its pin |
| `e` | Export the snapshot as Markdown to `export_dir` |
| `o` | Change the settings |
| `s` | Take a snapshot now |
| `t` | Switch between the dark and the light theme, and save it in the settings |
| `?` | Show all the keys |
| `q`, `esc` | Quit |

The restore opens new windows with the saved order, frame, titles, colors, splits and profiles. Each pane runs `omp --resume` or `claude --resume` in the agent folder, with the launch flags of the original session. A shell pane goes to its folder.

`ai-tabs` does not resume a session that still runs: two processes on the same session file corrupt it. For the same reason, when a snapshot holds one session in two panes, only the first pane resumes it.

### Commands

| Command | What it does |
|---|---|
| `ai-tabs` | Open the restore screen |
| `ai-tabs snapshot` | Take a snapshot now |
| `ai-tabs restore [--from ID] [--tab 1.3 …] [--all] [--here] [--dry-run]` | Restore tabs. Without `--tab` or `--all`, it opens the restore screen. `--here` opens the tabs in this window |
| `ai-tabs show [ID]` | Show the tabs and sessions of a snapshot |
| `ai-tabs history [--limit N]` | List the snapshots, newest first |
| `ai-tabs pin ID`, `ai-tabs unpin ID` | Pin a snapshot, or remove its pin |
| `ai-tabs export [ID …] [--to DIR]` | Write snapshots as Markdown files |
| `ai-tabs backup` | Write a backup of the database now |
| `ai-tabs config`, `config set KEY VALUE`, `config unset KEY` | Show or change the settings |
| `ai-tabs install`, `ai-tabs uninstall` | Load or remove the launchd agent |

A snapshot ID is `YYYY-MM-DD/HH-MM-SS`. `latest` is the newest snapshot. See [docs/cli.md](docs/cli.md) for all the options.

## Settings

A setting takes its value from, in order of priority:

1. the command option, for example `export --to`;
2. the environment variable `AI_TABS_DIR`, for `data_dir` only;
3. the configuration file `$XDG_CONFIG_HOME/ai-tabs/config.toml`, or `~/.config/ai-tabs/config.toml`;
4. the default.

| Setting | Default | Meaning |
|---|---|---|
| `data_dir` | `$XDG_DATA_HOME/ai-tabs`, or `~/.local/share/ai-tabs` | Folder of the database `ai-tabs.sqlite`. If `~/Library/Application Support/ai-tabs` exists, ai-tabs moves it to this folder at the first start |
| `export_dir` | `data_dir/export` | Folder of the Markdown exports |
| `export_latest` | `false` | Rewrite `export_dir/latest.md` after every new snapshot |
| `backup_dir` | `data_dir/backups` | Folder of the daily backups |
| `backup_keep` | `7` | How many daily backups stay |
| `history_days` | `30` | How many days the unpinned snapshots stay |
| `snapshot_interval` | `300` | Seconds between two snapshots. Run `ai-tabs install` after a change |
| `splash` | `true` | Show the logo for a moment when the restore screen opens, in iTerm2 |
| `theme` | `auto` | `auto`, `dark` or `light`. `auto` follows the macOS appearance |

The configuration file holds only the settings that you changed, with `config set`, the settings window (`o`) or the `t` key. The other settings take their defaults. `ai-tabs config` shows each value and where it comes from: `file`, `environment` or `default`. `ai-tabs config unset KEY` gives a setting its default again. A new `data_dir` takes effect at the next start.

For an Obsidian vault, put the Markdown exports in the vault and keep the database out of it. A sync tool or git can copy the database while it is open and corrupt the copy. The exports are text files:

```sh
ai-tabs config set export_dir ~/Notes/ai-tabs
ai-tabs config set export_latest true
```

## Data

- `ai-tabs snapshot` writes one backup a day with SQLite `VACUUM INTO`, which makes a consistent copy. To use a backup, stop the agent with `ai-tabs uninstall`, copy the backup over the database file, then run `ai-tabs install`.
- `ai-tabs export` writes one file per snapshot: `export_dir/YYYY-MM-DD/HH-MM-SS.md`. Each file has a front matter for Obsidian properties and Dataview, the changes, a table of the panes and the resume commands. Nothing reads the exports back: the database stays the only source.
- The launchd agent logs to `~/Library/Logs/ai-tabs.log`.

## How it finds the agent sessions

- **Claude Code**: `~/.claude/sessions/<pid>.json` gives the session ID and folder of each `claude` process.
- **omp**: `lsof` gives the session file that each `omp` process holds open. The first lines of the file give the session ID, folder and title.
- `ps` gives the terminal of each process, and its command line for the launch flags. `ps` drops the original quotes, so a flag value with spaces can split into more words.

## Limits

- Only iTerm2 on macOS.
- A reboot stops every process. `ai-tabs` opens the tabs again and resumes the sessions, but it does not bring back running processes.
- It resumes only omp and Claude Code sessions. Other panes go back to their folder.

## Development

```sh
uv sync
uv run pytest
uv run ruff check src tests
uv run typer ai_tabs.cli utils docs --name ai-tabs --title ai-tabs --output docs/cli.md
```

### Release

The `Release` workflow publishes to PyPI when a tag `vX.Y.Z` arrives on GitHub. It runs the tests, checks that the tag is the version in `pyproject.toml`, builds the wheel and the sdist, then uploads them with PyPI Trusted Publishing. No token is stored in GitHub.

Before a release, move the `[Unreleased]` entries of `CHANGELOG.md` to a new section for the version, with the date. Then:

```sh
uv version --bump minor   # or patch, major
git commit -am "chore: release v$(uv version --short)"
git tag "v$(uv version --short)"
git push origin main --tags
```

## License

MIT. See [LICENSE](LICENSE).

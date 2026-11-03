# Changelog

All the changes to ai-tabs that users can see. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-03

The first release.

### Added

- `ai-tabs snapshot` saves the iTerm2 windows, tabs and panes in a SQLite database. A snapshot holds the order, the frames, the titles, the tab colors, the splits, the pane sizes and the profiles. For each omp and Claude Code session, it also holds the session ID, the folder and the launch flags. The value of `--api-key` is not saved.
- `ai-tabs install` loads a launchd agent that takes a snapshot at login and every `snapshot_interval` seconds. `ai-tabs uninstall` removes it.
- The restore screen (`ai-tabs`) shows the snapshots and their tabs. You can search, select tabs, pin snapshots, see the changes, see the commands, export, take a snapshot and change the settings.
- `ai-tabs restore` opens the selected tabs again and resumes the agent sessions. In iTerm2, it asks where the tabs open: in new windows with the saved frames, or as new tabs in the current window (`--here`). It reports the agent sessions that do not start.
- `ai-tabs` does not resume a session that still runs, and it resumes a session only once when two panes hold it. Two processes on one session file corrupt it.
- Pins: `manual`, `before-boot` (the last snapshot before a reboot) and `before-drop` (the last snapshot before many tabs close). Pinned snapshots stay. After a reboot or a crash, the restore screen starts on the last snapshot from before it.
- `ai-tabs history`, `ai-tabs show`, `ai-tabs pin` and `ai-tabs unpin`.
- `ai-tabs export` writes Markdown files with a front matter for Obsidian. The `export_latest` setting rewrites `latest.md` after each new snapshot.
- Daily database backups with SQLite `VACUUM INTO`, and `ai-tabs backup`.
- `ai-tabs config`, `config set` and `config unset`. The settings file is `$XDG_CONFIG_HOME/ai-tabs/config.toml`, or `~/.config/ai-tabs/config.toml`.
- The data folder is `$XDG_DATA_HOME/ai-tabs`, or `~/.local/share/ai-tabs`. If `~/Library/Application Support/ai-tabs` exists, ai-tabs moves it there at the first start.
- A dark and a light theme in the colors of the logo. The `theme` setting is `auto` (the macOS appearance), `dark` or `light`. The `t` key switches the theme and saves the choice.
- A logo splash in iTerm2 (setting `splash`).

[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/WaYdotNET/ai-tabs/releases/tag/v0.1.0

# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.6.0] - 2026-11-10

### Added

- Setting `backup_times`: a list of times of day (`HH:MM`), default `09:00,17:00`. At its first run at or after each of these times, the interval agent prunes the old snapshots and writes the backup of the day, also on a day without changes. If the Mac sleeps at that time, this occurs at the first run after the wake. One backup file stays for each day: a later run replaces the file of the day. Use `ai-tabs config set backup_times 09:00,17:00` or the settings window.

### Changed

- When the database did not change since the newest backup, the daily backup writes no new copy. The newest backup gets the date of today and the time of now.
- A change of window frames or pane sizes only updates the newest snapshot. It does not add a snapshot. A pinned snapshot, or a snapshot from before the current boot, stays as it is.
- The watcher no longer prunes the snapshots or writes the backup.

## [0.5.0] - 2026-11-04

### Added

- The `f` key searches the tabs of all the snapshots, and restores a tab from the snapshot you pick.

## [0.4.1] - 2026-11-03

### Fixed

- The session list of the `r` key keeps its width with opencode sessions in a narrow terminal.

## [0.4.0] - 2026-11-03

### Added

- opencode and hermes sessions: snapshots, restore and `ai-tabs sessions`.
- The `r` key resumes recent sessions and the `l` key opens a saved layout, on the restore screen.
- `scripts/release.py` releases a new version in one command.

### Changed

- The watcher no longer takes a snapshot when a window only moves or changes size.

### Fixed

- A pane that runs a program saves the folder of that program, not the folder of the last prompt.

## [0.3.2] - 2026-11-03

### Changed

- The `c` key shows the ai-tabs commands, as `ai-tabs --help`. The `d` key shows the commands that restore runs.
- `ai-tabs changelog` and the `v` key show one line per change, with the version, the date and the kind.

## [0.3.1] - 2026-11-03

### Fixed

- The logo of the splash no longer stays visible behind the restore screen.
- The keys window wraps a long action under its own column.
- The commands window breaks a long command at the window width and keeps its indent.
- The windows of the restore screen are only as tall as their text.

## [0.3.0] - 2026-11-03

### Added

- `ai-tabs doctor` checks the whole setup in one command.
- `ai-tabs watch` and a second launchd agent: a snapshot about 2 seconds after a tab, window or pane change. Setting `watch`.
- `ai-tabs sessions` lists the recent omp and Claude Code sessions that do not run, and `--open` resumes them.
- `ai-tabs layout` saves, lists, shows, opens and deletes named layouts.
- `ai-tabs backup --list` and `ai-tabs backup --restore DATE`, with a safety copy of the current database.

### Fixed

- Two snapshots at the same moment no longer write the same snapshot twice or fail on the daily backup.

## [0.2.2] - 2026-11-03

### Fixed

- Snapshots find an omp session that has no new message after a resume. omp holds the session file open only while it writes, so ai-tabs now also reads the file from `omp --resume`. Before, the snapshot saved such a tab as a shell, and restore reported "did not start" for a session that ran.

## [0.2.1] - 2026-11-03

### Fixed

- Restore checks again which agent sessions run before it sends the commands. A session whose old tab closed after the restore screen opened now resumes, and no longer opens only its folder.

## [0.2.0] - 2026-11-03

### Added

- `ai-tabs --version`, `ai-tabs changelog`, and the `v` key on the restore screen.

### Fixed

- The links to `docs/cli.md` and `LICENSE` work on PyPI.

## [0.1.1] - 2026-11-03

### Fixed

- The logo shows on PyPI.

## [0.1.0] - 2026-11-03

First release.

- Snapshots of the iTerm2 tabs and of the omp and Claude Code sessions, every 5 minutes.
- Restore screen: pick the snapshot and the tabs, then open them in new windows or in this window.
- Pinned snapshots before a reboot or before many tabs close.
- Markdown export, daily backups, `config` command.
- Dark and light theme.

[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/WaYdotNET/ai-tabs/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/WaYdotNET/ai-tabs/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/WaYdotNET/ai-tabs/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/WaYdotNET/ai-tabs/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/WaYdotNET/ai-tabs/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/WaYdotNET/ai-tabs/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/WaYdotNET/ai-tabs/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/WaYdotNET/ai-tabs/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/WaYdotNET/ai-tabs/releases/tag/v0.1.0

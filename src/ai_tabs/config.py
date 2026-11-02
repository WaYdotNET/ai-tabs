"""Paths, fixed values and the user configuration of ai-tabs.

The configuration file is `~/.config/ai-tabs/config.toml`. It can hold these keys:

* `data_dir`: the folder of the snapshot database.
* `markdown_dir`: a folder for the Markdown views, for example a folder in an Obsidian vault.
  Without it, the command writes no Markdown.
* `backup_dir`: the folder of the daily database backups. The default is `data_dir/backups`.
* `backup_keep`: how many daily backups to keep. The default is 7.

The environment variable `AI_TABS_DIR` overrides `data_dir`.
"""

import json
import os
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HOME = Path.home()
CONFIG_FILE = HOME / ".config/ai-tabs/config.toml"
DEFAULT_DATA_DIR = HOME / "Library/Application Support/ai-tabs"
DATA_DIR_ENV = "AI_TABS_DIR"
DEFAULT_BACKUP_KEEP = 7
HISTORY_DAYS = 30

CLAUDE_PID_DIR = HOME / ".claude/sessions"
OMP_SESSION_DIR = HOME / ".omp/agent/sessions"

LAUNCHD_LABEL = "com.github.ai-tabs.snapshot"
LAUNCHD_PLIST = HOME / f"Library/LaunchAgents/{LAUNCHD_LABEL}.plist"
LAUNCHD_LOG = HOME / "Library/Logs/ai-tabs.log"
SNAPSHOT_INTERVAL_SECONDS = 300

# Fixed macOS paths: the PATH of launchd, sudo or a non-login shell can leave out /usr/sbin.
PS = "/bin/ps"
LSOF = "/usr/sbin/lsof"
OSASCRIPT = "/usr/bin/osascript"
SYSCTL = "/usr/sbin/sysctl"
LAUNCHCTL = "/bin/launchctl"


@dataclass(frozen=True)
class Settings:
    """Where the data goes. `markdown_dir` is None when the Markdown views are off."""

    data_dir: Path
    markdown_dir: Path | None
    backup_dir: Path
    backup_keep: int

    @property
    def database(self) -> Path:
        """Return the path of the snapshot database."""
        return self.data_dir / "ai-tabs.sqlite"


def read_config() -> dict[str, object]:
    """Return the keys of the configuration file, or an empty dict when there is no file."""
    if not CONFIG_FILE.exists():
        return {}
    return tomllib.loads(CONFIG_FILE.read_text())


def optional_path(value: object) -> Path | None:
    """Return a configured folder as a Path, or None when the key is missing or empty."""
    return Path(str(value)).expanduser() if value else None


@cache
def settings() -> Settings:
    """Return the settings from the environment, the configuration file and the defaults."""
    config = read_config()
    data_dir = optional_path(os.environ.get(DATA_DIR_ENV)) or optional_path(config.get("data_dir")) or DEFAULT_DATA_DIR
    backup_dir = optional_path(config.get("backup_dir")) or data_dir / "backups"
    backup_keep = int(config.get("backup_keep", DEFAULT_BACKUP_KEEP))
    return Settings(data_dir, optional_path(config.get("markdown_dir")), backup_dir, backup_keep)


def write_config(updates: dict[str, str | int]) -> None:
    """Merge keys into the configuration file and write it again.

    The file holds only flat keys. A JSON string is also a valid TOML basic string.
    """
    config = {**read_config(), **updates}
    lines = [f"{key} = {json.dumps(value)}" for key, value in sorted(config.items())]
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    settings.cache_clear()

"""Paths, fixed values and the settings of ai-tabs.

The settings come, in order of priority, from a command option, from the environment variable
`AI_TABS_DIR` (for `data_dir` only), from the configuration file, and from the defaults. The
configuration file is `$XDG_CONFIG_HOME/ai-tabs/config.toml`, or `~/.config/ai-tabs/config.toml`.
`ai-tabs config` and the settings window of the restore screen change it.
"""

import json
import os
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HOME = Path.home()
CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ai-tabs/config.toml"
DEFAULT_DATA_DIR = HOME / "Library/Application Support/ai-tabs"
DATA_DIR_ENV = "AI_TABS_DIR"

CLAUDE_PID_DIR = HOME / ".claude/sessions"
OMP_SESSION_DIR = HOME / ".omp/agent/sessions"

LAUNCHD_LABEL = "com.github.ai-tabs.snapshot"
LAUNCHD_PLIST = HOME / f"Library/LaunchAgents/{LAUNCHD_LABEL}.plist"
LAUNCHD_LOG = HOME / "Library/Logs/ai-tabs.log"

# Fixed macOS paths: the PATH of launchd, sudo or a non-login shell can leave out /usr/sbin.
PS = "/bin/ps"
LSOF = "/usr/sbin/lsof"
OSASCRIPT = "/usr/bin/osascript"
SYSCTL = "/usr/sbin/sysctl"
LAUNCHCTL = "/bin/launchctl"

SETTING_KINDS = {
    "data_dir": "folder",
    "export_dir": "folder",
    "export_latest": "true or false",
    "backup_dir": "folder",
    "backup_keep": "number",
    "history_days": "number",
    "snapshot_interval": "seconds",
    "splash": "true or false",
    "theme": "auto, dark or light",
}
SETTING_HELP = {
    "data_dir": "folder of the snapshot database",
    "export_dir": "folder of the Markdown exports",
    "export_latest": "rewrite export_dir/latest.md after every new snapshot",
    "backup_dir": "folder of the daily database backups",
    "backup_keep": "how many daily backups stay",
    "history_days": "how many days the unpinned snapshots stay",
    "snapshot_interval": "seconds between two snapshots of the launchd agent (run `ai-tabs install` after a change)",
    "splash": "show the logo for a moment when the restore screen opens",
    "theme": "colors of the restore screen; auto follows the macOS appearance",
}


@dataclass(frozen=True)
class Settings:
    """The settings that the commands use."""

    data_dir: Path
    export_dir: Path
    export_latest: bool
    backup_dir: Path
    backup_keep: int
    history_days: int
    snapshot_interval: int
    splash: bool
    theme: str

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
    """Return a configured folder as a Path, or None when the value is missing or empty."""
    return Path(str(value)).expanduser() if value else None


@cache
def settings() -> Settings:
    """Return the settings from the environment, the configuration file and the defaults."""
    config = read_config()
    data_dir = optional_path(os.environ.get(DATA_DIR_ENV)) or optional_path(config.get("data_dir")) or DEFAULT_DATA_DIR
    return Settings(
        data_dir=data_dir,
        export_dir=optional_path(config.get("export_dir")) or data_dir / "export",
        export_latest=bool(config.get("export_latest", False)),
        backup_dir=optional_path(config.get("backup_dir")) or data_dir / "backups",
        backup_keep=int(config.get("backup_keep", 7)),
        history_days=int(config.get("history_days", 30)),
        snapshot_interval=int(config.get("snapshot_interval", 300)),
        splash=bool(config.get("splash", True)),
        theme=str(config.get("theme", "auto")),
    )


def setting_source(key: str) -> str:
    """Return where the value of a setting comes from: `environment`, `file` or `default`."""
    if key == "data_dir" and os.environ.get(DATA_DIR_ENV):
        return "environment"
    return "file" if key in read_config() else "default"


def parse_setting(key: str, text: str) -> str | int | bool:
    """Return the value of a setting from its text, or raise ValueError when it is not valid."""
    kind = SETTING_KINDS.get(key)
    if kind is None:
        raise ValueError(f"unknown setting {key!r}; the settings are {', '.join(SETTING_KINDS)}")
    return PARSERS[kind](key, text)


def parse_folder(key: str, text: str) -> str:
    """Return a folder as an absolute path."""
    return str(Path(text).expanduser().resolve())


def parse_theme(key: str, text: str) -> str:
    """Return `auto`, `dark` or `light`, or raise ValueError."""
    if text.lower() not in ("auto", "dark", "light"):
        raise ValueError(f"{key} must be auto, dark or light, not {text!r}")
    return text.lower()


def parse_bool(key: str, text: str) -> bool:
    """Return `true` or `false` as a bool, or raise ValueError."""
    answers = {"true": True, "false": False}
    if text.lower() not in answers:
        raise ValueError(f"{key} must be true or false, not {text!r}")
    return answers[text.lower()]


def parse_positive(key: str, text: str) -> int:
    """Return a whole number greater than 0, or raise ValueError."""
    if not text.isdigit() or int(text) == 0:
        raise ValueError(f"{key} must be a whole number greater than 0, not {text!r}")
    return int(text)


PARSERS = {
    "folder": parse_folder,
    "true or false": parse_bool,
    "number": parse_positive,
    "seconds": parse_positive,
    "auto, dark or light": parse_theme,
}


def save_config(values: dict[str, object]) -> None:
    """Write exactly these keys to the configuration file. A JSON value is also valid TOML."""
    lines = [f"{key} = {json.dumps(value)}" for key, value in sorted(values.items())]
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text("\n".join(lines) + "\n" if lines else "")
    settings.cache_clear()


def write_config(updates: dict[str, object]) -> None:
    """Merge keys into the configuration file."""
    save_config({**read_config(), **updates})


def unset_config(key: str) -> None:
    """Remove a key from the configuration file, so that the setting takes its default again."""
    save_config({name: value for name, value in read_config().items() if name != key})


def setting_text(value: object) -> str:
    """Return a setting value as the text that `ai-tabs config set` accepts."""
    return str(value).lower() if isinstance(value, bool) else str(value)

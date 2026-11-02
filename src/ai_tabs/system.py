"""Small calls to macOS tools."""

import re
import subprocess
from datetime import datetime

from .config import SYSCTL

BOOT_TIME_RE = re.compile(r"sec = (\d+)")


def run(*command: str) -> str:
    """Run a command and return its stdout, or an empty string if it fails or does not exist."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def boot_time() -> datetime | None:
    """Return when the Mac started, in local time, or None when `sysctl` gives no answer."""
    match = BOOT_TIME_RE.search(run(SYSCTL, "-n", "kern.boottime"))
    return datetime.fromtimestamp(int(match.group(1))) if match else None

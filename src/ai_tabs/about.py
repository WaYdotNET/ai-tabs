"""The version of ai-tabs, and a short view of its changelog."""

import re
from dataclasses import dataclass
from importlib.resources import files

from rich.table import Table

from . import __version__
from .palette import Palette

# The package holds CHANGELOG.md as a symlink to the file at the root of the repository.
# The build copies the target, so that the installed package has the text.
CHANGELOG = files("ai_tabs") / "CHANGELOG.md"
RELEASE_RE = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\S+))?")
KIND_LABELS = {"Added": "new", "Changed": "changed", "Fixed": "fix", "Removed": "removed"}


@dataclass(frozen=True)
class Change:
    """One change of a release: its kind (`new`, `fix`, ...) and its first sentence."""

    kind: str
    text: str


@dataclass(frozen=True)
class Release:
    """A release of the changelog: its version, its date and its changes."""

    version: str
    date: str
    changes: tuple[Change, ...]


def version_text() -> str:
    """Return the name and the version, for example `ai-tabs 0.1.1`."""
    return f"ai-tabs {__version__}"


def first_sentence(text: str) -> str:
    """Return the first sentence of a changelog item, without Markdown backticks."""
    sentence, _, _ = text.replace("`", "").partition(". ")
    return sentence if sentence.endswith(".") else f"{sentence}."


def changes_in(lines: list[str]) -> tuple[Change, ...]:
    """Return the changes of the lines of one release. A `### Kind` heading sets the kind of the items after it.
    Items before any heading, as in the first release, are new."""
    kind, changes = "new", []
    for line in lines:
        if line.startswith("### "):
            kind = KIND_LABELS.get(line[4:].strip(), line[4:].strip().lower())
        elif line.startswith("- "):
            changes.append(Change(kind, first_sentence(line[2:])))
    return tuple(changes)


def release_blocks(text: str) -> list[list[str]]:
    """Split the changelog text into one list of lines per release. The first line of each list is its heading."""
    blocks = [block.splitlines() for block in re.split(r"^(?=## )", text, flags=re.MULTILINE)]
    return [block for block in blocks if block and RELEASE_RE.match(block[0])]


def release_from_block(block: list[str]) -> Release:
    """Build a Release from its heading line and the lines under it."""
    heading = RELEASE_RE.match(block[0])
    return Release(heading["version"], heading["date"] or "", changes_in(block[1:]))


def releases() -> list[Release]:
    """Return the releases of the changelog, newest first. A section without changes, such as an empty
    `Unreleased`, is left out."""
    found = [release_from_block(block) for block in release_blocks(CHANGELOG.read_text())]
    return [release for release in found if release.changes]


def changelog_view(colors: Palette) -> Table:
    """Return the releases as a grid: version and date on the first change of each release, then one line per
    change with its kind."""
    styles = {"new": colors.green, "fix": colors.gold}
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True, style=f"bold {colors.cyan}")
    grid.add_column(no_wrap=True, style=colors.muted)
    grid.add_column(no_wrap=True)
    grid.add_column()
    for release in releases():
        for index, change in enumerate(release.changes):
            first = index == 0
            grid.add_row(release.version if first else "", release.date if first else "",
                         f"[{styles.get(change.kind, colors.muted)}]{change.kind}[/]", change.text)
        grid.add_row()
    return grid

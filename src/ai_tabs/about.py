"""The version of ai-tabs and its changelog."""

from importlib.resources import files

from . import __version__

# The package holds CHANGELOG.md as a symlink to the file at the root of the repository.
# The build copies the target, so that the installed package has the text.
CHANGELOG = files("ai_tabs") / "CHANGELOG.md"


def version_text() -> str:
    """Return the name and the version, for example `ai-tabs 0.1.1`."""
    return f"ai-tabs {__version__}"


def changelog_text() -> str:
    """Return the releases of the changelog as Markdown, without the title and the link definitions."""
    text = CHANGELOG.read_text()
    releases = text[text.index("\n## "):].splitlines()
    return "\n".join(plain_heading(line) for line in releases if not line.startswith("[")).strip()


def plain_heading(line: str) -> str:
    """Remove the brackets of a release heading: `## [0.1.1] - date` becomes `## 0.1.1 - date`."""
    return line.replace("[", "").replace("]", "") if line.startswith("## ") else line

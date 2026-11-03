"""The version and the changelog that the package shows."""

from typer.testing import CliRunner

from ai_tabs import __version__
from ai_tabs.about import changelog_text
from ai_tabs.cli import app


def test_the_changelog_has_a_section_for_the_package_version():
    assert f"\n## {__version__} - " in changelog_text()


def test_the_changelog_starts_with_the_newest_section_and_has_no_link_definitions():
    text = changelog_text()

    assert text.startswith("## Unreleased")
    assert "]: https://" not in text


def test_version_option_prints_the_version_and_stops():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"ai-tabs {__version__}\n"

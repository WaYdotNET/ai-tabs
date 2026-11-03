"""The version, the short view of the changelog, and the command list of the restore screen."""

from typer.testing import CliRunner

from ai_tabs import __version__, about
from ai_tabs.about import Change, Release
from ai_tabs.cli import app, command_rows

FAKE_CHANGELOG = """# Changelog

Intro text.

## [Unreleased]

## [0.2.0] - 2026-11-03

### Added

- `ai-tabs doctor` checks the setup. It also checks the database.

### Fixed

- The logo shows on PyPI

## [0.1.0] - 2026-11-01

- First release.

[Unreleased]: https://example.com/compare/v0.2.0...HEAD
"""


def test_the_changelog_has_a_section_for_the_package_version():
    assert f"## [{__version__}] - " in about.CHANGELOG.read_text()


def test_releases_keep_one_line_per_change_and_leave_out_an_empty_section(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(FAKE_CHANGELOG)
    monkeypatch.setattr(about, "CHANGELOG", changelog)

    found = about.releases()

    assert found == [
        Release("0.2.0", "2026-11-03", (Change("new", "ai-tabs doctor checks the setup."),
                                        Change("fix", "The logo shows on PyPI."))),
        Release("0.1.0", "2026-11-01", (Change("new", "First release."),)),
    ]


def test_version_option_prints_the_version_and_stops():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"ai-tabs {__version__}\n"


def test_the_command_list_has_each_command_and_each_subcommand_with_the_first_sentence_of_its_help():
    rows = dict(command_rows())

    assert rows["ai-tabs history"] == "List the latest snapshots, newest first."
    assert rows["ai-tabs layout save"] == "Save tabs as a layout."
    assert rows["ai-tabs layout"] == "Save tabs under a name, and open them again later."

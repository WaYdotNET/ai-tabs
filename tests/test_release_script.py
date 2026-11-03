"""The changelog text change and the version math of scripts/release.py."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release.py"
spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

Intro text.

## [Unreleased]

### Fixed

- The watcher no longer stops.

## [0.3.2] - 2026-11-03

### Changed

- The `c` key shows the commands.

[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.1...v0.3.2
"""

EMPTY_UNRELEASED = """# Changelog

## [Unreleased]

## [0.3.2] - 2026-11-03

- The `c` key shows the commands.

[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.2...HEAD
"""


def released() -> str:
    """Return the test changelog after the release of 0.3.3."""
    return release.release_changelog(CHANGELOG, "0.3.2", "0.3.3", "2026-11-04")


def test_release_changelog_moves_the_items_to_the_new_section() -> None:
    text = released()

    assert "## [0.3.3] - 2026-11-04\n\n### Fixed\n\n- The watcher no longer stops.\n\n## [0.3.2]" in text


def test_release_changelog_keeps_an_empty_unreleased_section() -> None:
    text = released()

    assert "Intro text.\n\n## [Unreleased]\n\n## [0.3.3] - 2026-11-04\n" in text


def test_release_changelog_points_the_unreleased_link_at_the_new_tag() -> None:
    text = released()

    assert "[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.3...HEAD\n" in text


def test_release_changelog_adds_the_new_link_right_under_the_unreleased_link() -> None:
    text = released()

    assert text.endswith(
        "[Unreleased]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.3...HEAD\n"
        "[0.3.3]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.2...v0.3.3\n"
        "[0.3.2]: https://github.com/WaYdotNET/ai-tabs/compare/v0.3.1...v0.3.2\n"
    )


def test_release_changelog_moves_the_items_only_once() -> None:
    text = released()

    assert text.count("- The watcher no longer stops.") == 1


def test_release_changelog_refuses_an_empty_unreleased_section() -> None:
    with pytest.raises(release.ReleaseError, match="no item under"):
        release.release_changelog(EMPTY_UNRELEASED, "0.3.2", "0.3.3", "2026-11-04")


def test_release_changelog_refuses_a_changelog_without_unreleased_section() -> None:
    with pytest.raises(release.ReleaseError, match="no `## \\[Unreleased\\]` section"):
        release.release_changelog("# Changelog\n\n## [0.1.0] - 2026-11-01\n", "0.1.0", "0.1.1", "2026-11-04")


def test_release_changelog_refuses_a_changelog_without_unreleased_link() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n- A change.\n"

    with pytest.raises(release.ReleaseError, match="no `\\[Unreleased\\]: ` link"):
        release.release_changelog(text, "0.1.0", "0.1.1", "2026-11-04")


def test_bumped_version_patch_increments_the_last_number() -> None:
    assert release.bumped_version("0.3.2", "patch") == "0.3.3"


def test_bumped_version_minor_increments_the_middle_number_and_resets_patch() -> None:
    assert release.bumped_version("0.3.2", "minor") == "0.4.0"


def test_bumped_version_major_increments_the_first_number_and_resets_the_rest() -> None:
    assert release.bumped_version("0.3.2", "major") == "1.0.0"


def test_bumped_version_refuses_an_unknown_part() -> None:
    with pytest.raises(release.ReleaseError, match="Unknown part"):
        release.bumped_version("0.3.2", "build")

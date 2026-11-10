"""The changelog text change, the version math and the workflow wait of scripts/release.py."""

import importlib.util
import subprocess
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


def gh_answers(monkeypatch: pytest.MonkeyPatch, answers: list[tuple[int, str]]) -> None:
    """Make each `gh` call return the next exit code and stdout, and make the waits instant."""
    replies = iter(answers)

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        code, stdout = next(replies)
        return subprocess.CompletedProcess(argv, code, stdout, "HTTP 504")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)


def test_run_conclusion_waits_through_a_failed_gh_call_while_the_run_continues(monkeypatch) -> None:
    gh_answers(monkeypatch, [
        (0, '{"status": "in_progress", "conclusion": ""}'),
        (1, ""),
        (0, '{"status": "completed", "conclusion": "success"}'),
    ])

    assert release.run_conclusion(42) == "success"


def test_wait_for_release_workflow_stops_when_the_run_fails(monkeypatch) -> None:
    monkeypatch.setattr(release, "release_run", lambda _tag: {"databaseId": 42, "url": "https://run/42"})
    gh_answers(monkeypatch, [(0, '{"status": "completed", "conclusion": "failure"}')])

    with pytest.raises(release.ReleaseError, match="ended with 'failure': https://run/42"):
        release.wait_for_release_workflow("0.6.1")


def test_run_conclusion_stops_when_the_run_does_not_complete(monkeypatch) -> None:
    monkeypatch.setattr(release, "RUN_POLLS", 2)
    gh_answers(monkeypatch, [(0, '{"status": "queued", "conclusion": ""}')] * 2)

    with pytest.raises(release.ReleaseError, match="did not complete"):
        release.run_conclusion(42)

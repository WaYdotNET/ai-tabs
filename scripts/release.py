"""Release ai-tabs: bump the version, update the changelog, tag, push, wait for PyPI and install.

Usage: uv run scripts/release.py patch|minor|major [--dry-run]

This script is a development tool. It is not part of the package.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import date
from pathlib import Path

from ai_tabs.config import WATCH_LAUNCHD_LABEL

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"
COMPARE_URL = "https://github.com/WaYdotNET/ai-tabs/compare"
PYPI_JSON = "https://pypi.org/pypi/ai-tabs/json"
UNRELEASED = "## [Unreleased]"
UNRELEASED_LINK = "[Unreleased]: "
PARTS = ("patch", "minor", "major")
# The PyPI index and its CDN can lag a few minutes behind the upload.
PYPI_POLLS = 40
PYPI_POLL_SECONDS = 15
INSTALL_ATTEMPTS = 10
INSTALL_RETRY_SECONDS = 30
RUN_APPEAR_POLLS = 20
RUN_APPEAR_SECONDS = 6
RUN_POLLS = 180
RUN_POLL_SECONDS = 10


class ReleaseError(Exception):
    """A release step failed. The message tells the user what to do."""


def run(argv: list[str]) -> str:
    """Run argv without a shell in the repository root, and return its stdout. Raise on a non-zero exit code."""
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise ReleaseError(f"`{' '.join(argv)}` failed with exit code {result.returncode}.\n{output}")
    return result.stdout.strip()


def succeeds(argv: list[str]) -> bool:
    """Return True when argv exits with code 0. Use it only for a probe, never for a step."""
    return subprocess.run(argv, cwd=ROOT, capture_output=True, check=False).returncode == 0


def step(text: str) -> None:
    """Print the one line of a step."""
    print(f"• {text}", flush=True)


def bumped_version(old: str, part: str) -> str:
    """Return the version after a bump of `part` (patch, minor or major) of `old`."""
    major, minor, patch = (int(number) for number in old.split("."))
    bumps = {
        "patch": (major, minor, patch + 1),
        "minor": (major, minor + 1, 0),
        "major": (major + 1, 0, 0),
    }
    if part not in bumps:
        raise ReleaseError(f"Unknown part {part!r}. Use patch, minor or major.")
    return ".".join(str(number) for number in bumps[part])


def unreleased_bounds(lines: list[str]) -> tuple[int, int]:
    """Return the index of the Unreleased header and the index of the next release header."""
    if UNRELEASED not in lines:
        raise ReleaseError(f"CHANGELOG.md has no `{UNRELEASED}` section.")
    start = lines.index(UNRELEASED)
    later_headers = [index for index in range(start + 1, len(lines)) if lines[index].startswith("## [")]
    return start, later_headers[0] if later_headers else len(lines)


def unreleased_items(text: str) -> list[str]:
    """Return the lines of the Unreleased section, without the blank lines at its start and end."""
    lines = text.splitlines()
    start, end = unreleased_bounds(lines)
    body = "\n".join(lines[start + 1 : end]).strip("\n")
    if not body.strip():
        raise ReleaseError(f"CHANGELOG.md has no item under `{UNRELEASED}`. Add the changes of this release first.")
    return body.splitlines()


def release_links(lines: list[str], old: str, new: str) -> list[str]:
    """Point the Unreleased link at v<new> and add the link of the new release right under it."""
    starts = [index for index, line in enumerate(lines) if line.startswith(UNRELEASED_LINK)]
    if not starts:
        raise ReleaseError(f"CHANGELOG.md has no `{UNRELEASED_LINK}` link.")
    index = starts[0]
    unreleased = f"{UNRELEASED_LINK}{COMPARE_URL}/v{new}...HEAD"
    release = f"[{new}]: {COMPARE_URL}/v{old}...v{new}"
    return [*lines[:index], unreleased, release, *lines[index + 1 :]]


def release_changelog(text: str, old: str, new: str, today: str) -> str:
    """Return the changelog with the Unreleased items moved to a new `<new> - <today>` section."""
    items = unreleased_items(text)
    lines = text.splitlines()
    start, end = unreleased_bounds(lines)
    section = [UNRELEASED, "", f"## [{new}] - {today}", "", *items, ""]
    moved = [*lines[:start], *section, *lines[end:]]
    return "\n".join(release_links(moved, old, new)) + "\n"


def check_preconditions() -> None:
    """Stop unless the work tree is a clean `main` that is equal to `origin/main`, with Unreleased items."""
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch != "main":
        raise ReleaseError(f"The branch is {branch!r}. Release only from `main`.")
    if run(["git", "status", "--porcelain"]):
        raise ReleaseError("The work tree is not clean. Commit or stash the changes first.")
    run(["git", "fetch", "origin"])
    if run(["git", "rev-parse", "main"]) != run(["git", "rev-parse", "origin/main"]):
        raise ReleaseError("`main` is not equal to `origin/main`. Pull or push first.")
    unreleased_items(CHANGELOG.read_text())
    step("Preconditions: clean `main`, equal to `origin/main`, with Unreleased items.")


def project_version() -> str:
    """Return the version in pyproject.toml."""
    return tomllib.loads(PYPROJECT.read_text())["project"]["version"]


def check_tag_is_free(new: str) -> None:
    """Stop when the tag v<new> exists locally or on origin."""
    tag = f"v{new}"
    if run(["git", "tag", "--list", tag]):
        raise ReleaseError(f"The tag {tag} exists locally.")
    if run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"]):
        raise ReleaseError(f"The tag {tag} exists on origin.")


def new_version(part: str) -> tuple[str, str]:
    """Return the current and the new version, after a check that the new tag is free."""
    old = project_version()
    new = bumped_version(old, part)
    check_tag_is_free(new)
    step(f"Version: {old} -> {new}. The tag v{new} is free.")
    return old, new


def update_changelog(old: str, new: str) -> None:
    """Write the new release section into CHANGELOG.md."""
    CHANGELOG.write_text(release_changelog(CHANGELOG.read_text(), old, new, date.today().isoformat()))
    step(f"CHANGELOG.md: section [{new}] with the Unreleased items.")


def bump_version(part: str) -> None:
    """Bump the version in pyproject.toml and update uv.lock."""
    run(["uv", "version", "--bump", part])
    run(["uv", "lock"])
    step(f"Version bump ({part}) and uv.lock.")


def regenerate_docs() -> None:
    """Regenerate docs/cli.md from the Typer app."""
    run(["uv", "run", "typer", "ai_tabs.cli", "utils", "docs", "--name", "ai-tabs", "--title", "ai-tabs",
         "--output", "docs/cli.md"])  # fmt: skip
    step("docs/cli.md regenerated.")


def run_gates() -> None:
    """Run ruff and the test suite."""
    run(["uv", "run", "ruff", "check", "src", "tests"])
    run(["uv", "run", "pytest", "-q"])
    step("Gates: ruff and pytest pass.")


def commit_tag_push(new: str) -> None:
    """Commit the release, tag it and push `main` with the tag."""
    tag = f"v{new}"
    run(["git", "add", "--all"])
    run(["git", "commit", "-m", f"chore: release {tag}"])
    run(["git", "tag", tag])
    run(["git", "push", "origin", "main", tag])
    step(f"Commit, tag {tag} and push.")


def release_run(tag: str) -> dict:
    """Return the Release workflow run of the tag. Wait until GitHub lists it."""
    argv = ["gh", "run", "list", "--workflow", "release.yml", "--branch", tag, "--limit", "1",
            "--json", "databaseId,url"]  # fmt: skip
    for _ in range(RUN_APPEAR_POLLS):
        runs = json.loads(run(argv))
        if runs:
            return runs[0]
        time.sleep(RUN_APPEAR_SECONDS)
    raise ReleaseError(f"GitHub lists no Release workflow run for {tag}.")


def run_state(run_id: int) -> dict | None:
    """Return the status and the conclusion of a workflow run, or None when `gh` fails.

    A failed `gh` call is often a temporary GitHub API error, so the caller asks again.
    """
    argv = ["gh", "run", "view", str(run_id), "--json", "status,conclusion"]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    return json.loads(result.stdout) if result.returncode == 0 else None


def run_conclusion(run_id: int) -> str:
    """Wait until a workflow run completes and return its conclusion.

    `gh run watch --exit-status` is not used: it exits with an error when one of its own API calls
    fails, also while the run continues.
    """
    for _ in range(RUN_POLLS):
        state = run_state(run_id)
        if state is not None and state["status"] == "completed":
            return state["conclusion"]
        time.sleep(RUN_POLL_SECONDS)
    raise ReleaseError(f"The workflow run {run_id} did not complete in {RUN_POLLS * RUN_POLL_SECONDS} seconds.")


def wait_for_release_workflow(new: str) -> None:
    """Wait for the Release workflow of v<new>, and stop with its URL when it does not succeed."""
    workflow = release_run(f"v{new}")
    conclusion = run_conclusion(workflow["databaseId"])
    if conclusion != "success":
        raise ReleaseError(f"The Release workflow ended with {conclusion!r}: {workflow['url']}")
    step(f"Release workflow passed: {workflow['url']}")


def pypi_version() -> str:
    """Return the latest version that the PyPI JSON API reports. Return an empty string when PyPI fails."""
    try:
        with urllib.request.urlopen(PYPI_JSON, timeout=30) as response:
            return json.load(response)["info"]["version"]
    except OSError:
        return ""


def wait_for_pypi(new: str) -> None:
    """Wait until the PyPI JSON API reports the new version."""
    for _ in range(PYPI_POLLS):
        if pypi_version() == new:
            step(f"PyPI reports {new}.")
            return
        time.sleep(PYPI_POLL_SECONDS)
    raise ReleaseError(f"PyPI does not report {new} after {PYPI_POLLS * PYPI_POLL_SECONDS} seconds.")


def install_pinned(new: str) -> None:
    """Install ai-tabs==<new> as a uv tool. Retry, because the index can lag behind the JSON API."""
    argv = ["uv", "tool", "install", "--force", "--refresh", f"ai-tabs=={new}"]
    for _ in range(INSTALL_ATTEMPTS - 1):
        if succeeds(argv):
            return
        time.sleep(INSTALL_RETRY_SECONDS)
    run(argv)


def install_release(new: str) -> None:
    """Install the new release, remove the pin, restart the watcher and run the doctor."""
    install_pinned(new)
    run(["uv", "tool", "install", "--force", "ai-tabs"])
    installed = run(["ai-tabs", "-V"])
    if new not in installed:
        raise ReleaseError(f"`ai-tabs -V` reports {installed!r}, not {new}.")
    watcher = f"gui/{os.getuid()}/{WATCH_LAUNCHD_LABEL}"
    if succeeds(["launchctl", "print", watcher]):
        run(["launchctl", "kickstart", "-k", watcher])
    run(["ai-tabs", "doctor"])
    step(f"Installed {installed}, restarted the watcher when loaded, doctor passes.")


def print_plan(part: str, old: str, new: str) -> None:
    """Print the steps that a real release runs after the checks, and the new changelog section."""
    today = date.today().isoformat()
    plan = [
        f"CHANGELOG.md: section [{new}] - {today}, links v{new}...HEAD and v{old}...v{new}.",
        f"uv version --bump {part}, then uv lock.",
        "Regenerate docs/cli.md.",
        "Gates: uv run ruff check src tests, uv run pytest -q.",
        f"Commit `chore: release v{new}`, tag v{new}, git push origin main v{new}.",
        f"Wait for the Release workflow of v{new}.",
        f"Wait for PyPI {new}, uv tool install ai-tabs=={new}, then unpinned, ai-tabs -V, watcher, doctor.",
    ]
    print("Dry run. A real release also runs these steps:")
    for line in plan:
        print(f"  - {line}")
    section = "\n".join(unreleased_items(CHANGELOG.read_text()))
    print(f"\nNew changelog section:\n\n## [{new}] - {today}\n\n{section}")


def release(part: str) -> None:
    """Run all the release steps in order."""
    check_preconditions()
    old, new = new_version(part)
    update_changelog(old, new)
    bump_version(part)
    regenerate_docs()
    run_gates()
    commit_tag_push(new)
    wait_for_release_workflow(new)
    wait_for_pypi(new)
    install_release(new)


def dry_run(part: str) -> None:
    """Run the read-only checks and print the rest of the plan. Change nothing."""
    check_preconditions()
    old, new = new_version(part)
    print_plan(part, old, new)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Release ai-tabs to PyPI.")
    parser.add_argument("part", choices=PARTS, help="The part of the version to bump.")
    parser.add_argument("--dry-run", action="store_true", help="Run only the checks and print the plan.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the release or the dry run. Return the exit code."""
    args = parse_args(argv)
    action = dry_run if args.dry_run else release
    try:
        action(args.part)
    except ReleaseError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

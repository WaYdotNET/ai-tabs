"""The move of the macOS data folder to the XDG data folder."""

import pytest

from ai_tabs import config


@pytest.fixture
def folders(monkeypatch, isolated_data):
    """Use a temporary old folder with a database, and a temporary default folder that does not exist."""
    monkeypatch.delenv(config.DATA_DIR_ENV)
    old, new = isolated_data / "Application Support/ai-tabs", isolated_data / "share/ai-tabs"
    monkeypatch.setattr(config, "LEGACY_DATA_DIR", old)
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", new)
    old.mkdir(parents=True)
    (old / "ai-tabs.sqlite").write_text("snapshots")
    return old, new


def test_the_old_folder_moves_to_the_default_folder(folders):
    old, new = folders

    moved_from = config.move_legacy_data()

    assert moved_from == old
    assert (new / "ai-tabs.sqlite").read_text() == "snapshots"
    assert not old.exists()


def test_an_existing_default_folder_stops_the_move(folders):
    old, new = folders
    new.mkdir(parents=True)

    moved_from = config.move_legacy_data()

    assert moved_from is None
    assert (old / "ai-tabs.sqlite").read_text() == "snapshots"


def test_a_configured_data_dir_stops_the_move(folders, isolated_data):
    old, _ = folders
    config.write_config({"data_dir": str(isolated_data / "elsewhere")})

    moved_from = config.move_legacy_data()

    assert moved_from is None
    assert (old / "ai-tabs.sqlite").read_text() == "snapshots"

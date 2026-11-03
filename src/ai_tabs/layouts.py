"""Named layouts: sets of windows and tabs that stay until you delete them.

A layout lives in the snapshot database, in its own table. The history prune never deletes it.
"""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from . import store
from .models import Window, windows_from_json, windows_to_json

NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
NAME_MAX = 40
NAME_RULE = f"1 to {NAME_MAX} characters: letters, digits, '-', '_' and '.'"

SCHEMA = """
CREATE TABLE IF NOT EXISTS layouts (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    windows TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Layout:
    """A named set of windows, with the time when it was saved."""

    name: str
    created_at: datetime
    windows: list[Window]


def name_problem(name: str) -> str | None:
    """Return why a layout name is not valid, or None when it is valid."""
    if not name or len(name) > NAME_MAX:
        return f"the name has {len(name)} characters. A layout name has {NAME_RULE}"
    if NAME_PATTERN.fullmatch(name) is None:
        return f"the name {name!r} has characters that are not permitted. A layout name has {NAME_RULE}"
    return None


@contextmanager
def layout_database() -> Iterator[sqlite3.Connection]:
    """Open the database with `store.database` and create the layouts table when needed."""
    with store.database() as db:
        db.executescript(SCHEMA)
        yield db


def layout_from_row(row: sqlite3.Row) -> Layout:
    """Build a Layout from a database row."""
    return Layout(row["name"], datetime.fromisoformat(row["created_at"]), windows_from_json(row["windows"]))


def save_layout(name: str, windows: list[Window], moment: datetime) -> bool:
    """Store a layout under a name. Return True when it replaced a layout with the same name.

    Raise ValueError when the name is not valid.
    """
    problem = name_problem(name)
    if problem is not None:
        raise ValueError(problem)
    values = (name, f"{moment:%Y-%m-%d %H:%M:%S}", windows_to_json(windows))
    with layout_database() as db:
        existed = db.execute("SELECT 1 FROM layouts WHERE name = ?", (name,)).fetchone() is not None
        db.execute("INSERT OR REPLACE INTO layouts (name, created_at, windows) VALUES (?, ?, ?)", values)
    return existed


def find_layout(name: str) -> Layout | None:
    """Return the layout with a name, or None when there is none."""
    with layout_database() as db:
        row = db.execute("SELECT name, created_at, windows FROM layouts WHERE name = ?", (name,)).fetchone()
    return layout_from_row(row) if row else None


def all_layouts() -> list[Layout]:
    """Return every layout, sorted by name."""
    with layout_database() as db:
        rows = db.execute("SELECT name, created_at, windows FROM layouts ORDER BY name").fetchall()
    return [layout_from_row(row) for row in rows]


def layout_names() -> list[str]:
    """Return the names of the layouts, sorted."""
    with layout_database() as db:
        return [row["name"] for row in db.execute("SELECT name FROM layouts ORDER BY name")]


def delete_layout(name: str) -> bool:
    """Delete the layout with a name. Return False when there is no layout with that name."""
    with layout_database() as db:
        return db.execute("DELETE FROM layouts WHERE name = ?", (name,)).rowcount == 1

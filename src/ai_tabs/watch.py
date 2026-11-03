"""Watch iTerm2 and take a snapshot when a tab, a window or a pane opens or closes."""

import asyncio
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial

import iterm2
from iterm2.notifications import async_subscribe_to_layout_change_notification
from websockets.exceptions import WebSocketException

from .iterm import iterm_is_running
from .snapshot import take_snapshot

PREFIX = "watch: "
QUIET_SECONDS = 2.0
RETRY_SECONDS = 10.0
SNAPSHOT_ERRORS = (sqlite3.Error, OSError, iterm2.RPCException, WebSocketException)


class Debouncer:
    """Run an action once for each burst of events, when no event came for `quiet` seconds."""

    def __init__(self, action: Callable[[], Awaitable[None]], quiet: float) -> None:
        self.action = action
        self.quiet = quiet
        self.pending = asyncio.Event()

    def poke(self) -> None:
        """Record an event. The action runs `quiet` seconds after the last event of the burst."""
        self.pending.set()

    async def run(self) -> None:
        """Run the action after each burst, until the task stops.

        An event that comes while the action runs starts a new burst, so that no change goes unseen.
        """
        while True:
            await self.pending.wait()
            await self.quiet_time()
            await self.action()

    async def quiet_time(self) -> None:
        """Return when no event came for `quiet` seconds."""
        while True:
            self.pending.clear()
            try:
                await asyncio.wait_for(self.pending.wait(), self.quiet)
            except TimeoutError:
                return


def log(text: str) -> None:
    """Write a line to the log, with the time and the `watch:` prefix."""
    print(f"{PREFIX}{datetime.now():%H:%M:%S} {text}")


async def logged_snapshot(connection: iterm2.Connection) -> None:
    """Take a snapshot with the `watch:` prefix. Log a failed snapshot, so that the watcher goes on."""
    try:
        await take_snapshot(connection, PREFIX)
    except SNAPSHOT_ERRORS as error:
        log(f"The snapshot failed: {error!r}")


async def watch_layout(connection: iterm2.Connection) -> None:
    """Take a snapshot after each burst of layout changes, until iTerm2 closes the connection.

    A layout change comes when a tab, a window or a pane opens, closes or moves, and when a window
    changes its size. An error that `logged_snapshot` does not expect stops the watcher.
    """
    debouncer = Debouncer(partial(logged_snapshot, connection), QUIET_SECONDS)

    async def on_layout_change(_connection: iterm2.Connection, _message: object) -> None:
        debouncer.poke()

    await async_subscribe_to_layout_change_notification(connection, on_layout_change)
    log("Connected to iTerm2.")
    worker = asyncio.create_task(debouncer.run())
    closed = asyncio.create_task(connection.websocket.wait_closed())
    finished, _ = await asyncio.wait([worker, closed], return_when=asyncio.FIRST_COMPLETED)
    worker.cancel()
    closed.cancel()
    # Debouncer.run never returns: a finished worker holds an error.
    if worker in finished:
        worker.result()
    log("iTerm2 closed the connection.")


def watch_once() -> None:
    """Watch iTerm2 until it closes the connection. Return at once when iTerm2 does not run.

    The check comes first, so that the log stays quiet while iTerm2 does not run: a failed
    connection writes a long message to the log.
    """
    if not iterm_is_running():
        return
    try:
        iterm2.Connection().run_until_complete(watch_layout, retry=False)
    except ConnectionRefusedError:
        log("Cannot connect to iTerm2. Turn on its Python API in the iTerm2 settings.")


def watch_iterm() -> None:
    """Watch iTerm2 forever. Between two connections, wait RETRY_SECONDS, so that the loop does not spin."""
    sys.stdout.reconfigure(line_buffering=True)
    while True:
        watch_once()
        time.sleep(RETRY_SECONDS)

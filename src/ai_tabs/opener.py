"""Open the saved windows, tabs and panes in iTerm2."""

import asyncio
import contextlib
from dataclasses import dataclass
from itertools import pairwise

import iterm2
from rich.markup import escape
from websockets.exceptions import ConnectionClosed

from .agents import find_agent
from .display import console, tab_heading
from .models import Agent, Pane, Tab, Window
from .plan import pane_command

PROMPT_TIMEOUT = 10
START_CHECKS = 20
START_CHECK_INTERVAL = 1

SplitStep = tuple[int, int, bool]
"""One split: the index of the pane to split, the index of the new pane, and if the divider is vertical."""


@dataclass(frozen=True)
class Target:
    """The iTerm2 connection and app that restore opens windows in, and the profile names that exist."""

    connection: iterm2.Connection
    app: iterm2.App
    profiles: frozenset[str]


@dataclass(frozen=True)
class Resumed:
    """An agent session that restore resumes in a new iTerm2 session."""

    heading: str
    agent: Agent
    session: iterm2.Session


def first_pane(node: dict) -> int:
    """Return the first pane of a layout node: the pane that holds the whole node before its splits."""
    return node["pane"] if "pane" in node else first_pane(node["children"][0])


def node_split_steps(node: dict) -> list[SplitStep]:
    """Return the splits that build a layout node from its first pane.

    Each child after the first splits from the previous child, in the orientation of the node.
    The splits inside a child come after, when the child holds all its space.
    """
    if "pane" in node:
        return []
    children = node["children"]
    steps = [(first_pane(before), first_pane(after), node["vertical"]) for before, after in pairwise(children)]
    for child in children:
        steps += node_split_steps(child)
    return steps


def split_steps(layout: dict | None, pane_count: int) -> list[SplitStep]:
    """Return the splits that build the panes of a tab, in order.

    Without a layout the panes open side by side, each split from the one before.
    """
    if layout is None:
        return [(index - 1, index, True) for index in range(1, pane_count)]
    return node_split_steps(layout)


def known_profile(name: str | None, profiles: frozenset[str]) -> str | None:
    """Return the profile name if the profile exists, else None, the default profile of iTerm2."""
    return name if name in profiles else None


def tab_profile(target: Target, saved: Tab) -> str | None:
    """Return the profile that opens a tab: the profile of its first pane."""
    first = saved.panes[0].profile if saved.panes else None
    return known_profile(first, target.profiles)


async def profile_names(connection: iterm2.Connection) -> frozenset[str]:
    """Return the names of the iTerm2 profiles."""
    profiles = await iterm2.PartialProfile.async_query(connection)
    return frozenset(profile.name for profile in profiles if profile.name)


def tab_color_change(color: list[int]) -> iterm2.LocalWriteOnlyProfile:
    """Return a profile change that shows the color in light mode, in dark mode and in a profile
    without separate colors, so that the tab shows it whatever the profile and the mode are."""
    value = iterm2.Color(*color)
    change = iterm2.LocalWriteOnlyProfile()
    for set_color, set_use in ((change.set_tab_color, change.set_use_tab_color),
                               (change.set_tab_color_light, change.set_use_tab_color_light),
                               (change.set_tab_color_dark, change.set_use_tab_color_dark)):
        set_color(value)
        set_use(True)
    return change


async def apply_tab_style(tab: iterm2.Tab, saved: Tab, sessions: list[iterm2.Session]) -> None:
    """Set the saved title and color on a new tab and its sessions."""
    if saved.title:
        await tab.async_set_title(saved.title)
    if saved.color is None:
        return
    change = tab_color_change(saved.color)
    for session in sessions:
        await session.async_set_profile_properties(change)


async def open_panes(target: Target, first: iterm2.Session, saved: Tab) -> list[iterm2.Session]:
    """Split the first session of a new tab into the saved panes. Return the sessions in pane order."""
    sessions = {0: first}
    for source, new, vertical in split_steps(saved.layout, len(saved.panes)):
        profile = known_profile(saved.panes[new].profile, target.profiles)
        sessions[new] = await sessions[source].async_split_pane(vertical=vertical, before=False, profile=profile)
    return [sessions[index] for index in range(len(saved.panes))]


async def apply_sizes(target: Target, tab_id: str, saved: Tab, sessions: list[iterm2.Session]) -> None:
    """Resize the panes of a new tab to their saved sizes in characters.

    The app refreshes first, because its layout notifications can arrive after the last split.
    """
    sizes = {session.session_id: iterm2.Size(pane.columns, pane.rows)
             for session, pane in zip(sessions, saved.panes, strict=True) if pane.columns and pane.rows}
    if len(sizes) < 2:
        return
    await target.app.async_refresh()
    tab = target.app.get_tab_by_id(tab_id)
    for session in tab.sessions:
        session.preferred_size = sizes.get(session.session_id, session.preferred_size)
    await tab.async_update_layout()


async def wait_for_prompt(connection: iterm2.Connection, session_id: str) -> None:
    """Wait until the shell of the session shows its prompt, for at most PROMPT_TIMEOUT seconds.

    The monitor starts before the check, so that a prompt that shows between the two is not lost.
    """
    async with iterm2.PromptMonitor(connection, session_id, modes=[iterm2.PromptMonitor.Mode.PROMPT]) as monitor:
        if await iterm2.async_get_last_prompt(connection, session_id) is not None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(monitor.async_get(), PROMPT_TIMEOUT)


async def start_pane(connection: iterm2.Connection, session: iterm2.Session, pane: Pane) -> None:
    """Send the pane command to the session when its shell is ready."""
    await wait_for_prompt(connection, session.session_id)
    await session.async_send_text(pane_command(pane) + "\n")


def resumes_agent(pane: Pane) -> bool:
    """Tell if the pane command resumes the agent session of the pane."""
    return pane.agent is not None and pane_command(pane) == pane.agent.resume


async def fill_tab(target: Target, tab: iterm2.Tab, saved: Tab) -> list[Resumed]:
    """Open the saved panes in a new tab and send each one its command.

    Return the agent sessions that the tab resumes.
    """
    sessions = await open_panes(target, tab.current_session, saved)
    await apply_tab_style(tab, saved, sessions)
    await apply_sizes(target, tab.tab_id, saved, sessions)
    opened = list(zip(sessions, saved.panes, strict=True))
    await asyncio.gather(*(start_pane(target.connection, session, pane) for session, pane in opened))
    heading = tab_heading(saved)
    return [Resumed(heading, pane.agent, session) for session, pane in opened if resumes_agent(pane)]


async def restore_window(target: Target, saved: Window) -> list[Resumed]:
    """Open one saved window with all its tabs, then move it to its saved frame.

    The frame is set last: iTerm2 ignores a frame set before the window finishes its layout.
    Return the agent sessions that the window resumes.
    """
    window = await iterm2.Window.async_create(target.connection, profile=tab_profile(target, saved.tabs[0]))
    resumed = []
    for index, saved_tab in enumerate(saved.tabs):
        tab = window.current_tab if index == 0 else await window.async_create_tab(
            profile=tab_profile(target, saved_tab))
        resumed += await fill_tab(target, tab, saved_tab)
    x, y, width, height = saved.frame
    await window.async_set_frame(iterm2.Frame(iterm2.Point(x, y), iterm2.Size(width, height)))
    return resumed


def is_same_session(found: Agent | None, agent: Agent) -> bool:
    """Tell if the agent found on a tty runs the saved session."""
    return found is not None and found.session_id == agent.session_id


async def agent_started(resumed: Resumed) -> bool:
    """Tell if the resumed session runs on its tty within START_CHECKS checks.

    The check only watches: a second resume of the same session can corrupt its session file.
    """
    tty = await resumed.session.async_get_variable("tty") or ""
    for _ in range(START_CHECKS):
        if is_same_session(await asyncio.to_thread(find_agent, tty), resumed.agent):
            return True
        await asyncio.sleep(START_CHECK_INTERVAL)
    return False


async def report_not_started(resumed: list[Resumed]) -> None:
    """Print one line for each resumed agent session that does not start."""
    started = await asyncio.gather(*(agent_started(item) for item in resumed))
    failed = [item for item, ok in zip(resumed, started, strict=True) if not ok]
    for item in failed:
        console.print(f"[yellow]did not start[/yellow]  {escape(item.heading)}  "
                      f"{item.agent.kind} {item.agent.session_id}")


def ignore_closed_connection(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Hide the errors of iTerm2 API tasks that fail because the connection closed. Show the others.

    The iterm2 library leaves App refresh tasks behind. They fail when `run_until_complete`
    closes the connection, and asyncio prints them as "Task exception was never retrieved".
    """
    if not isinstance(context.get("exception"), ConnectionClosed):
        loop.default_exception_handler(context)


def open_windows(windows: list[Window]) -> None:
    """Open the windows in iTerm2, then report the agent sessions that do not start."""

    async def restore_all(connection: iterm2.Connection) -> None:
        asyncio.get_running_loop().set_exception_handler(ignore_closed_connection)
        # The App object registers the delegate that Window.async_create_tab needs.
        app = await iterm2.async_get_app(connection)
        target = Target(connection, app, await profile_names(connection))
        resumed = []
        for window in windows:
            resumed += await restore_window(target, window)
        await report_not_started(resumed)

    iterm2.run_until_complete(restore_all)

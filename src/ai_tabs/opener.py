"""Open the saved windows, tabs and panes in iTerm2."""

import iterm2

from .models import Tab, Window
from .plan import pane_command


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


async def apply_tab_style(tab: iterm2.Tab, saved: Tab) -> None:
    """Set the saved title and color on a new tab."""
    if saved.title:
        await tab.async_set_title(saved.title)
    if saved.color is None:
        return
    change = tab_color_change(saved.color)
    for session in tab.sessions:
        await session.async_set_profile_properties(change)


async def fill_tab(tab: iterm2.Tab, saved: Tab) -> None:
    """Open the saved panes in a new tab and send each one its command.

    Extra panes open as vertical splits.
    """
    session = tab.current_session
    for index, pane in enumerate(saved.panes):
        if index:
            session = await session.async_split_pane(vertical=True)
        await session.async_send_text(pane_command(pane) + "\n")
    await apply_tab_style(tab, saved)


async def restore_window(connection: iterm2.Connection, saved: Window) -> None:
    """Open one saved window with all its tabs, then move it to its saved frame.

    The frame is set last: iTerm2 ignores a frame set before the window finishes its layout.
    """
    window = await iterm2.Window.async_create(connection)
    for index, saved_tab in enumerate(saved.tabs):
        tab = window.current_tab if index == 0 else await window.async_create_tab()
        await fill_tab(tab, saved_tab)
    x, y, width, height = saved.frame
    await window.async_set_frame(iterm2.Frame(iterm2.Point(x, y), iterm2.Size(width, height)))


def open_windows(windows: list[Window]) -> None:
    """Open the windows in iTerm2."""

    async def restore_all(connection: iterm2.Connection) -> None:
        # The App object registers the delegate that Window.async_create_tab needs.
        await iterm2.async_get_app(connection)
        for window in windows:
            await restore_window(connection, window)

    iterm2.run_until_complete(restore_all)

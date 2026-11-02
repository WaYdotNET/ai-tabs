"""The ai-tabs logo as colored text, in the colors of a palette."""

from rich.console import Group
from rich.text import Text

from .palette import Palette


def styled_line(*parts: tuple[str, str]) -> Text:
    """Return one line of text made of (text, style) parts."""
    line = Text()
    for value, style in parts:
        line.append(value, style=style)
    return line


def logo_compact(colors: Palette) -> Text:
    """Return the one-line logo for the top bar and the keys window of the restore screen."""
    return styled_line(("▰", colors.cyan), ("▰", colors.purple), ("▰", colors.green),
                       ("  >_ ", f"bold {colors.foreground}"), ("↻ ", f"bold {colors.gold}"),
                       ("ai-", f"bold {colors.foreground}"), ("tabs", f"bold {colors.cyan}"))


def logo_full(colors: Palette) -> Group:
    """Return the logo of six lines: a terminal window with three colored tabs, and the name."""
    frame, text = colors.muted, colors.foreground
    return Group(
        styled_line(("  ╭──────────────────────────╮", frame)),
        styled_line(("  │ ", frame), ("● ", colors.red), ("● ", colors.gold), ("●", colors.green),
                    ("                    │", frame)),
        styled_line(("  │ ", frame), ("▔▔▔▔▔▔", colors.cyan), (" ", text), ("▔▔▔▔▔▔", colors.purple), (" ", text),
                    ("▔▔▔▔▔▔", colors.green), ("     │", frame)),
        styled_line(("  │ ", frame), (">_", f"bold {text}"), (" " * 18, text), ("↻", f"bold {colors.gold}"),
                    ("    │", frame)),
        styled_line(("  ╰──────────────────────────╯", frame)),
        styled_line(("       ", text), ("ai-", f"bold {text}"), ("tabs", f"bold {colors.cyan}"), ("  ", text),
                    ("restore your flow", frame)),
    )

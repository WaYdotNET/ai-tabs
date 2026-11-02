"""The ai-tabs logo as colored text, for the restore screen and any Rich console."""

from rich.console import Group
from rich.text import Text

CYAN = "#19DCEB"
PURPLE = "#AE72F5"
GREEN = "#40E789"
GOLD = "#FFBD28"
RED = "#FF6464"
WHITE = "#EAF2FF"
MUTED = "#7187A6"


def styled_line(*parts: tuple[str, str]) -> Text:
    """Return one line of text made of (text, style) parts."""
    line = Text()
    for value, style in parts:
        line.append(value, style=style)
    return line


def logo_compact() -> Text:
    """Return the one-line logo for the top bar of the restore screen."""
    return styled_line(("▰", CYAN), ("▰", PURPLE), ("▰", GREEN), ("  >_ ", f"bold {WHITE}"),
                       ("↻ ", f"bold {GOLD}"), ("ai-", f"bold {WHITE}"), ("tabs", f"bold {CYAN}"))


def logo_full() -> Group:
    """Return the logo of six lines: a terminal window with three colored tabs, and the name."""
    return Group(
        styled_line(("  ╭──────────────────────────╮", MUTED)),
        styled_line(("  │ ", MUTED), ("● ", RED), ("● ", GOLD), ("●", GREEN), ("                    │", MUTED)),
        styled_line(("  │ ", MUTED), ("▔▔▔▔▔▔", CYAN), (" ", WHITE), ("▔▔▔▔▔▔", PURPLE), (" ", WHITE),
                    ("▔▔▔▔▔▔", GREEN), ("     │", MUTED)),
        styled_line(("  │ ", MUTED), (">_", f"bold {WHITE}"), (" " * 18, WHITE), ("↻", f"bold {GOLD}"),
                    ("    │", MUTED)),
        styled_line(("  ╰──────────────────────────╯", MUTED)),
        styled_line(("       ", WHITE), ("ai-", f"bold {WHITE}"), ("tabs", f"bold {CYAN}"), ("  ", WHITE),
                    ("restore your flow", MUTED)),
    )

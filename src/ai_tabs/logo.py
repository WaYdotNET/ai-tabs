"""The ai-tabs logo as colored text, and the colors of the logo that the restore screen uses."""

from rich.console import Group
from rich.text import Text

# Colors sampled from assets/logo.png. PURPLE is lighter than the logo purple, which is too
# dark to read on the navy background.
CYAN = "#01EAFC"
PURPLE = "#AE72F5"
GREEN = "#52FA74"
GOLD = "#FCB60D"
RED = "#FF6464"
WHITE = "#FBFBFC"
MUTED = "#7187A6"
NAVY = "#081637"
NAVY_DEEP = "#010A2D"
NAVY_LIGHT = "#092852"
BLUE = "#023468"


def styled_line(*parts: tuple[str, str]) -> Text:
    """Return one line of text made of (text, style) parts."""
    line = Text()
    for value, style in parts:
        line.append(value, style=style)
    return line


def logo_compact() -> Text:
    """Return the one-line logo for the top bar and the keys window of the restore screen."""
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

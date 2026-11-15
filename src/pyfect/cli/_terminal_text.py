"""Text from outside written to a terminal: file names, paths, messages.

A control character in such text (ESC starting CSI or OSC, C1's CSI) drives the terminal:
it can clear the screen, rewrite lines already shown or set the clipboard. Every piece of
text the CLI did not write itself goes through ``escape_control`` before it is shown.
"""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def escape_control(text: str, *, keep: str = "") -> str:
    """``text`` with each C0 and C1 control character and DEL written as ``\\xNN``, except
    those in ``keep``."""

    def escaped(match: re.Match[str]) -> str:
        found = match.group()
        return found if found in keep else f"\\x{ord(found):02x}"

    return _CONTROL.sub(escaped, text)

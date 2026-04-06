"""Text processing utilities — pure Python, no CLI dependencies.

All functions in this module are stateless and side-effect-free.
They operate on strings and return strings.
"""

from __future__ import annotations

import re

# ANSI escape sequence pattern.
# Matches: ESC [ <params> <final-byte>
# where <params> is any sequence of digits, semicolons, spaces and colons,
# and <final-byte> is a letter in the range 0x40–0x7E.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;:<=>?]*[ !\"#$%&'()*+,\-.\/]*[@-~]")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*.

    This is a pure-Python implementation — it does NOT shell out to any
    external tool.  Suitable for processing tool output that may contain
    colour codes (e.g. mutmut's progress bar) before storing or parsing.

    Parameters
    ----------
    text:
        Raw string potentially containing ANSI escape sequences.

    Returns
    -------
    str
        The input string with all ANSI sequences stripped.

    Examples
    --------
    >>> strip_ansi("\\x1b[32mhello\\x1b[0m world")
    'hello world'
    >>> strip_ansi("no escapes here")
    'no escapes here'
    >>> strip_ansi("")
    ''
    """
    return _ANSI_ESCAPE_RE.sub("", text)

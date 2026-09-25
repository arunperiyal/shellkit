"""
Quote-aware splitting of command lines.

`;` chains commands and `|` pipes them, but neither counts inside quotes:
`plot --title "A; B"` is one command, `case show "A|B"` has no pipe.
"""

import re
from typing import List

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


def split_unquoted(line: str, sep: str) -> List[str]:
    """
    Split `line` on `sep`, ignoring separators inside quotes or after a backslash.

    Parameters:
        line (str): Command line
        sep (str): Single separator character, e.g. ';' or '|'

    Returns:
        list: The stripped pieces, empty ones included

    Examples:
        'cmd1; cmd2'               -> ['cmd1', 'cmd2']
        'plot --title "A; B"; x'   -> ['plot --title "A; B"', 'x']
    """
    pieces = []
    current = []
    quote = None
    escape = False

    for char in line:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == '\\':
            escape = True
            current.append(char)
            continue
        if char in ('"', "'"):
            if quote is None:
                quote = char
            elif char == quote:
                quote = None
            current.append(char)
        elif char == sep and quote is None:
            pieces.append(''.join(current).strip())
            current = []
        else:
            current.append(char)

    pieces.append(''.join(current).strip())
    return pieces


def has_unquoted(line: str, sep: str) -> bool:
    """Return True if `sep` appears in `line` outside quotes."""
    return len(split_unquoted(line, sep)) > 1


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, so captured output pipes as plain text."""
    return _ANSI_RE.sub('', text)

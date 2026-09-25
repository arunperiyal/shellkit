"""
Shell builtins: commands handled by the shell itself rather than argparse.

Builtins come in bundles an app opts into by name:

    core   exit, help, clear, history, alias, unalias, use, unuse, set
    files  cd, pwd, ls, cat, head, tail, grep, tree, cp, rm, vi/vim/nano

An app adds its own with App.builtin().
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Union


@dataclass
class Builtin:
    """
    One builtin.

    Attributes:
        name: What the user types
        handler: (runtime, argv) -> int or None. argv excludes the name.
        help: One line for `help`
        usage: Usage line, e.g. 'head [-n N] <file>'
        details: Longer rich-markup text for `help <name>` / `<name> --help`
        complete: 'path' for path completion, or
                  (runtime, args_before, prefix) -> values to offer
        aliases: Other names for the same builtin (`quit`, `q` for `exit`)
        category: Heading it is listed under in `help`
        own_help: The handler deals with -h/--help itself
        hidden: Left out of the `help` overview (still completes and runs)
    """
    name: str
    handler: Callable[[Any, list], Optional[int]]
    help: str = ''
    usage: str = ''
    details: str = ''
    complete: Union[str, Callable, None] = None
    aliases: Sequence[str] = ()
    category: str = 'Shell'
    own_help: bool = False
    hidden: bool = False


def load_bundle(name: str):
    """Return the list of Builtins in a named bundle."""
    if name == 'core':
        from shellkit.builtins import core
        return core.builtins()
    if name == 'files':
        from shellkit.builtins import files
        return files.builtins()
    raise ValueError(f"Unknown builtin bundle: {name} (available: core, files)")

"""
Tab completion generated from the argparse tree.

Commands get completion without a hand-kept table: subcommand names and their
help, flags and their help, `choices`, context values for add_context_arg()
arguments, and anything an argument declares itself:

    p.add_argument('file').completer = paths(exts=('.othd', '.oisd'))
    p.add_argument('--to').completer = lambda rt, prefix: list_remotes()

A completer is (runtime, prefix) -> iterable of values, (value, meta) pairs
or (value, meta, display) triples. Values not starting with the prefix are dropped for it.

complete() is plain Python so it can be tested without a terminal;
ShellkitCompleter adapts it to prompt_toolkit.
"""

import argparse
import shlex
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from prompt_toolkit.completion import Completer, Completion

from shellkit.text import split_unquoted


@dataclass
class Candidate:
    """One completion: replace the last `replace` characters with `text`."""
    text: str
    replace: int
    meta: str = ''
    display: Optional[str] = None


# -- completers an app can attach to arguments ------------------------------------

def paths(exts: Sequence[str] = (), dirs_only: bool = False):
    """
    Completer for filesystem paths relative to the shell's cwd.

    Parameters:
        exts: Only offer files with these suffixes (directories are always
              offered, or there would be no way to walk down to the file)
        dirs_only: Offer only directories
    """
    exts = tuple(e.lower() for e in exts)

    def complete(rt, prefix):
        return path_candidates(rt, prefix, exts, dirs_only)

    return complete


def path_candidates(rt, prefix: str, exts: Sequence[str] = (),
                    dirs_only: bool = False) -> List[tuple]:
    """(value, meta, display) tuples for the paths starting with `prefix`."""
    if '/' in prefix:
        dir_part, name_part = prefix.rsplit('/', 1)
        base = rt.resolve_path(dir_part or '/')
        dir_part += '/'
    else:
        dir_part, name_part = '', prefix
        base = rt.cwd

    try:
        entries = [p for p in base.iterdir() if p.name.startswith(name_part)]
    except OSError:
        return []

    if not name_part.startswith('.'):
        entries = [p for p in entries if not p.name.startswith('.')]

    results = []
    for entry in sorted(entries, key=lambda p: (not p.is_dir(), p.name.lower())):
        is_dir = entry.is_dir()
        if not is_dir and (dirs_only or (exts and entry.suffix.lower() not in exts)):
            continue
        shown = entry.name + ('/' if is_dir else '')
        results.append((dir_part + shown, 'dir' if is_dir else 'file', shown))
    return results


# -- the completer ---------------------------------------------------------------

def complete(rt, text: str) -> List[Candidate]:
    """Completions for the line `text` (everything before the cursor)."""
    segment = split_unquoted(text, ';')[-1]
    segment = split_unquoted(segment, '|')[-1]
    words = _split_words(segment)
    new_word = not segment or text.endswith((' ', '\t'))
    if new_word:
        before, current = words, ''
    else:
        before, current = words[:-1], words[-1]

    if not before:
        return _first_word(rt, current)

    name = before[0]
    if name in rt.aliases:
        expanded = _split_words(rt.aliases[name])
        if expanded:
            before = expanded + before[1:]
            name = before[0]

    if name.startswith('!'):
        return _filter(path_candidates(rt, current), current)

    builtin = rt.builtins.get(name)
    if builtin is not None:
        return _builtin(rt, builtin, before[1:], current)

    if name in rt.app.command_names():
        return _argparse(rt, rt.parser, before, current)
    return []


def _split_words(segment: str) -> List[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        # an unterminated quote while typing: fall back to whitespace
        return segment.split()


def _first_word(rt, current: str) -> List[Candidate]:
    options = []
    for cmd in rt.app.registry.all():
        options.append((cmd.name, cmd.description))
    for name, builtin in rt.builtins.items():
        options.append((name, builtin.help))
    for name, expansion in rt.aliases.items():
        options.append((name, f'alias → {expansion}'))
    return _filter(options, current)


def _builtin(rt, builtin, args: List[str], current: str) -> List[Candidate]:
    if builtin.complete is None:
        return []
    if builtin.complete == 'path':
        if current.startswith('-'):
            return []
        return _filter(path_candidates(rt, current), current)
    return _filter(builtin.complete(rt, args, current), current)


def _argparse(rt, parser: argparse.ArgumentParser, words: List[str],
              current: str) -> List[Candidate]:
    """Walk `words` through the parser tree, then complete `current`."""
    index = 0              # position among the current parser's positionals
    pending = None         # option still waiting for its value
    pending_left = 0
    used_flags = set()

    for word in words:
        if pending is not None:
            pending_left -= 1
            if pending_left <= 0:
                pending = None
            continue
        if word.startswith('-') and len(word) > 1 and not _is_number(word):
            flag, has_value = word.split('=', 1)[0], '=' in word
            action = parser._option_string_actions.get(flag)
            if action is not None:
                used_flags.update(action.option_strings)
                takes = _values_taken(action)
                if takes and not has_value:
                    pending, pending_left = action, takes
            continue

        positionals = _positionals(parser)
        if index >= len(positionals):
            continue
        action = positionals[index]
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices.get(word)
            if sub is None:
                return []
            parser, index, used_flags = sub, 0, set()
            continue
        if action.nargs not in ('*', '+', argparse.REMAINDER):
            index += 1

    if pending is not None:
        return _filter(_action_values(rt, pending, current), current)

    if current.startswith('-'):
        return _flags(parser, current, used_flags)

    positionals = _positionals(parser)
    if index < len(positionals):
        action = positionals[index]
        if isinstance(action, argparse._SubParsersAction):
            return _filter(_subcommands(action), current)
        values = _filter(_action_values(rt, action, current), current)
        if values or current:
            return values
    return _flags(parser, current, used_flags) if current == '' else []


def _positionals(parser) -> list:
    return [a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)
            or (not a.option_strings and a.dest != argparse.SUPPRESS)]


def _values_taken(action) -> int:
    if action.nargs == 0 or isinstance(action, (argparse._StoreTrueAction,
                                                argparse._StoreFalseAction,
                                                argparse._CountAction,
                                                argparse._HelpAction,
                                                argparse._VersionAction)):
        return 0
    if isinstance(action.nargs, int):
        return action.nargs
    if action.nargs == '?':
        return 1
    return 1


def _is_number(word: str) -> bool:
    try:
        float(word)
        return True
    except ValueError:
        return False


def _subcommands(action) -> List[tuple]:
    help_for = {a.dest: a.help or '' for a in action._choices_actions}
    return [(name, help_for.get(name, '')) for name in action.choices]


def _flags(parser, current: str, used: set) -> List[Candidate]:
    options = []
    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        repeatable = isinstance(action, (argparse._AppendAction, argparse._CountAction))
        if not repeatable and used.intersection(action.option_strings):
            continue
        long_flags = [f for f in action.option_strings if f.startswith('--')]
        for flag in long_flags or action.option_strings:
            options.append((flag, action.help or ''))
    return _filter(options, current)


def _action_values(rt, action, current: str) -> Iterable:
    completer = getattr(action, 'completer', None)
    if completer is not None:
        return completer(rt, current)
    key_name = getattr(action, 'context_key', None)
    if key_name is not None:
        key = rt.context.keys.get(key_name)
        if key is not None:
            return context_values(rt, key, current)
    if action.choices is not None:
        return [str(c) for c in action.choices]
    return []


def context_values(rt, key, prefix: str) -> Iterable:
    """Values offered for a context key."""
    if key.complete is not None:
        return key.complete(rt, prefix)
    if key.path:
        return path_candidates(rt, prefix)
    return []


def _filter(options: Iterable, current: str) -> List[Candidate]:
    """Keep the options starting with `current`, as Candidates."""
    results = []
    seen = set()
    for option in options:
        if isinstance(option, Candidate):
            results.append(option)
            continue
        display = None
        if isinstance(option, (tuple, list)):
            value = str(option[0])
            meta = str(option[1]) if len(option) > 1 else ''
            display = option[2] if len(option) > 2 else None
        else:
            value, meta = str(option), ''
        if not value.startswith(current) or value in seen:
            continue
        seen.add(value)
        results.append(Candidate(value, len(current), meta, display))
    return results


class ShellkitCompleter(Completer):
    """prompt_toolkit adapter over complete()."""

    def __init__(self, runtime):
        self.runtime = runtime

    def get_completions(self, document, complete_event):
        try:
            candidates = complete(self.runtime, document.text_before_cursor)
        except Exception:
            # a broken completer must never take the prompt down
            return
        for c in candidates:
            yield Completion(c.text, start_position=-c.replace,
                             display=c.display, display_meta=c.meta)

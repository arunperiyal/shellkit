"""
Session context: values set once with `use` that commands pick up.

An app declares its keys:

    ContextKey('case', parse=resolve_case, path=True, label='c')
    ContextKey('node', parse=int, label='n')
    ContextKey('time', parse=float, clears=('t1', 't2'))

and a command asks for one where it takes the argument:

    add_context_arg(parser, 'case')              # positional, may be omitted
    add_context_arg(parser, 'node', '--node', type=int)

After parsing, any context argument the user left out is filled from the
context. There is no table of token positions to keep in step with the parser.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass
class ContextKey:
    """
    One context the user can set with `use name:value`.

    Attributes:
        name: Token name, as in `use case:C1`
        parse: raw str -> value. Takes (raw) or (raw, runtime); the second form
               can resolve against the cwd or other contexts. Raises
               ValueError for a bad value.
        description: Shown by `use --help` and completion
        complete: (runtime, prefix) -> values to offer after `name:`
        path: Complete filesystem paths when no `complete` is given
        label: Short label in the prompt (default: name)
        style: prompt_toolkit style for the prompt label, e.g. '#00aaff bold'
        format: value -> text shown in the prompt (default: the raw text)
        clears: Keys cleared when this one is set (`time` clears `t1`, `t2`)
    """
    name: str
    parse: Callable[..., Any] = str
    description: str = ''
    complete: Optional[Callable[[Any, str], Iterable]] = None
    path: bool = False
    label: Optional[str] = None
    style: Optional[str] = None
    format: Optional[Callable[[Any], str]] = None
    clears: Sequence[str] = ()

    def parse_value(self, raw: str, runtime=None) -> Any:
        if _takes_runtime(self.parse):
            return self.parse(raw, runtime)
        return self.parse(raw)

    def display(self, entry: 'ContextValue') -> str:
        if self.format is not None:
            return self.format(entry.value)
        return entry.raw


def _takes_runtime(fn) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False  # builtins such as int, float
    return len(params) >= 2


@dataclass
class ContextValue:
    """A set context: what was typed, and what it parsed to."""
    raw: str
    value: Any


class ContextError(Exception):
    """A context token that could not be applied."""


class ContextStore:
    """The context values currently set, in declaration order."""

    def __init__(self, keys: Sequence[ContextKey] = ()):
        self.keys: Dict[str, ContextKey] = {}
        for key in keys:
            self.add_key(key)
        self._values: Dict[str, ContextValue] = {}

    def add_key(self, key: ContextKey) -> None:
        if key.name in self.keys:
            raise ValueError(f"Context '{key.name}' is already declared")
        self.keys[key.name] = key

    # -- reading ------------------------------------------------------------

    def get(self, name: str, default: Any = None) -> Any:
        entry = self._values.get(name)
        return entry.value if entry is not None else default

    def entry(self, name: str) -> Optional[ContextValue]:
        return self._values.get(name)

    def raw(self, name: str) -> Optional[str]:
        entry = self._values.get(name)
        return entry.raw if entry is not None else None

    def is_set(self, name: str) -> bool:
        return name in self._values

    def items(self) -> List[Tuple[ContextKey, ContextValue]]:
        """Set contexts in declaration order."""
        return [(key, self._values[name]) for name, key in self.keys.items()
                if name in self._values]

    def tokens(self) -> List[str]:
        """Everything set, as `use` tokens."""
        return [f"{key.name}:{entry.raw}" for key, entry in self.items()]

    # -- writing ------------------------------------------------------------

    def set(self, name: str, raw: str, runtime=None) -> Any:
        """
        Parse and set one context.

        Raises:
            ContextError: Unknown key, empty value, or a value parse rejected
        """
        key = self.keys.get(name)
        if key is None:
            raise ContextError(
                f"Unknown context: {name} (valid: {', '.join(self.keys)})")
        raw = raw.strip()
        if not raw:
            raise ContextError(f"Missing value for context: {name}")
        try:
            value = key.parse_value(raw, runtime)
        except (TypeError, ValueError) as e:
            raise ContextError(f"Invalid {name} '{raw}': {e}") from e
        for other in key.clears:
            self._values.pop(other, None)
        self._values[name] = ContextValue(raw, value)
        return value

    def clear(self, name: str) -> bool:
        """Clear one context. Returns False if it was not set."""
        if name not in self.keys:
            raise ContextError(f"Unknown context: {name}")
        return self._values.pop(name, None) is not None

    def clear_all(self) -> None:
        self._values.clear()

    def apply_tokens(self, tokens: Iterable[str], runtime=None) -> Tuple[List[str], List[str]]:
        """
        Apply `name:value` tokens.

        Every token is tried, so one bad token does not stop the others.

        Returns:
            (applied tokens, error messages)
        """
        applied, errors = [], []
        for token in tokens:
            if ':' not in token:
                errors.append(f"Invalid format: {token} (use name:value)")
                continue
            name, raw = token.split(':', 1)
            name = name.strip().lower()
            try:
                self.set(name, raw, runtime)
            except ContextError as e:
                errors.append(str(e))
                continue
            applied.append(f"{name}:{raw.strip()}")
        return applied, errors


# -- context arguments ----------------------------------------------------------

class ContextDefault:
    """
    Default value marking an argument to fill from the context.

    argparse only applies `type` to string defaults, so this object survives
    parsing untouched and fill_context() can find it on the namespace.
    """

    def __init__(self, key: str, required: bool):
        self.key = key
        self.required = required

    def __repr__(self):
        return f"<from context: {self.key}>"


class MissingContext(Exception):
    """A required context argument was neither given nor set with `use`."""

    def __init__(self, key: str, dest: str):
        super().__init__(key)
        self.key = key
        self.dest = dest


def add_context_arg(parser, key: str, *flags: str, required: bool = True, **kwargs):
    """
    Add an argument that falls back to the `key` context when omitted.

    Parameters:
        parser: The (sub)parser to add to
        key: Context key name
        flags: Option strings such as '--node'. None gives a positional
               named `key` with nargs='?'.
        required: If True, a missing argument with no context set is an error.
                  If False it is left as None.
        kwargs: Passed to add_argument (type, help, metavar, ...)

    Returns:
        The argparse Action. Its `context_key` attribute drives completion.
    """
    if not flags:
        flags = (key,)
    if not flags[0].startswith('-'):
        kwargs.setdefault('nargs', '?')
    kwargs['default'] = ContextDefault(key, required)
    kwargs.setdefault('help', f"(default: the `use {key}:` context)")
    action = parser.add_argument(*flags, **kwargs)
    action.context_key = key
    return action


def fill_context(namespace, store: ContextStore) -> List[Tuple[str, ContextValue]]:
    """
    Replace every ContextDefault on `namespace` with the context's value.

    Returns:
        (key, value) pairs that were filled, for the "Using case: ..." echo

    Raises:
        MissingContext: A required context argument had no context set
    """
    used = []
    for dest, value in vars(namespace).items():
        if not isinstance(value, ContextDefault):
            continue
        entry = store.entry(value.key)
        if entry is not None:
            setattr(namespace, dest, entry.value)
            used.append((value.key, entry))
        elif value.required:
            raise MissingContext(value.key, dest)
        else:
            setattr(namespace, dest, None)
    return used

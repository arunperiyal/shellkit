"""
Program settings changed with `set <name> <value>` and kept in settings.json.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence


def parse_bool(raw: str) -> bool:
    """'on'/'off', 'true'/'false', 'yes'/'no', '1'/'0'."""
    value = str(raw).strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f"expected on/off, got '{raw}'")


def non_negative_int(raw) -> int:
    value = int(raw)
    if value < 0:
        raise ValueError(f"expected a non-negative integer, got '{raw}'")
    return value


@dataclass
class Setting:
    """
    One setting.

    Attributes:
        name: What the user types after `set`
        default: Value when nothing is stored (or the stored value is invalid)
        parse: raw str -> value; raises ValueError for a bad value
        help: One line for `set` with no arguments
        choices: Values offered by completion
        key: Key in settings.json (default: name). Lets an app keep the key an
             older version wrote, e.g. `timeout` stored as `timeout_minutes`.
        on_change: Called with (runtime, value) after the value changes
    """
    name: str
    default: Any
    parse: Callable[[str], Any] = str
    help: str = ''
    choices: Sequence[str] = ()
    key: Optional[str] = None
    on_change: Optional[Callable[[Any, Any], None]] = None

    @property
    def storage_key(self) -> str:
        return self.key or self.name


class Settings:
    """
    Declared settings plus any other keys the app keeps in settings.json.

    `data` is the whole file, so the framework's own bookkeeping (such as the
    last context) lives next to the declared settings without being one.
    """

    def __init__(self, storage, specs: Sequence[Setting] = ()):
        self._storage = storage
        self.specs = {spec.name: spec for spec in specs}
        self.data = storage.load_json(storage.SETTINGS, {})

    def add(self, spec: Setting) -> None:
        self.specs[spec.name] = spec

    def get(self, name: str) -> Any:
        """
        Current value of a declared setting.

        A stored value that no longer parses (edited by hand, or written by an
        older version) falls back to the default rather than failing.
        """
        spec = self.specs[name]
        if spec.storage_key not in self.data:
            return spec.default
        try:
            return spec.parse(self.data[spec.storage_key])
        except (TypeError, ValueError):
            return spec.default

    def set(self, name: str, raw: str) -> Any:
        """
        Parse and store a setting.

        Raises:
            KeyError: Unknown setting
            ValueError: Value does not parse
        """
        spec = self.specs[name]
        value = spec.parse(raw)
        self.data[spec.storage_key] = value
        self.save()
        return value

    def save(self) -> None:
        self._storage.save_json(self._storage.SETTINGS, self.data)

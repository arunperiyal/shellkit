"""
Per-app storage directory for history, aliases and settings.

`~/.flexflow` keeps them per user; `./.refman` keeps them with the project
the shell was started in. The file names match what flexflow already writes
(history, aliases, settings.json), so existing files carry over.
"""

import json
from pathlib import Path
from typing import Any, Optional


class Storage:
    """
    A directory of small files belonging to one app.

    The directory is created on the first write, not on construction, so an
    app that never saves anything leaves nothing behind.
    """

    HISTORY = 'history'
    ALIASES = 'aliases'
    SETTINGS = 'settings.json'

    def __init__(self, directory, base_dir: Optional[Path] = None):
        """
        Parameters:
            directory: '~/.name' for per-user storage, a relative path such as
                       '.name' for storage inside base_dir
            base_dir: What a relative directory is relative to (default: cwd)
        """
        path = Path(directory).expanduser()
        if not path.is_absolute():
            path = (base_dir or Path.cwd()) / path
        self.directory = path

    def path(self, name: str, create: bool = False) -> Path:
        """Path of a file in the storage directory, creating the directory if asked."""
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory / name

    @property
    def history_file(self) -> Path:
        return self.path(self.HISTORY, create=True)

    def load_json(self, name: str, default: Any) -> Any:
        """
        Load a JSON file, returning `default` if it is absent, corrupt, or not
        the same type as `default`.
        """
        path = self.path(name)
        if not path.exists():
            return default
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return default
        if default is not None and not isinstance(data, type(default)):
            return default
        return data

    def save_json(self, name: str, data: Any) -> None:
        """Write `data` as indented JSON."""
        with open(self.path(name, create=True), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

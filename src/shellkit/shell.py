"""
Interactive shell: the prompt loop around a Runtime.

History (deduplicated), completion, a two-line prompt showing the directory
and the context, and an optional session timeout that ends an idle shell.
"""

import html
import os
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import List

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from shellkit.completion import ShellkitCompleter

# Remembered context, restored by `use last`
LAST_CONTEXT_KEY = 'last_use_context_tokens'

DEFAULT_STYLES = {
    'path': '#888888',
    'box': '#666666',
    'sep': '#444444',
    'timeout': '#ff6666 bold',
    'ctx': '#00aaff',
}


class SessionTimeout(BaseException):
    """
    Raised by the alarm to break out of a waiting prompt.

    A BaseException, so a command's `except Exception` cannot swallow it.
    """


class InteractiveShell:
    """
    The prompt loop.

    Attributes:
        runtime: The Runtime executing each line
        session: prompt_toolkit PromptSession
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self.app = runtime.app
        runtime.interactive = True
        runtime.shell = self

        self.history_file = runtime.storage.history_file
        compact_history(self.history_file)
        self.session = self._create_session()

        self._timeout_enabled = self.app.session_timeout is not None
        self._deadline = 0.0
        self._timed_out = False
        self._previous_sigalrm = None
        self._at_prompt = False
        if self._timeout_enabled:
            self.reset_timeout()
            self._install_alarm()

    # -- prompt ---------------------------------------------------------------------

    def _create_session(self) -> PromptSession:
        styles = dict(DEFAULT_STYLES)
        for key in self.runtime.context.keys.values():
            styles[f'ctx-{key.name}'] = key.style or DEFAULT_STYLES['ctx']
        styles.update(self.app.prompt_styles)
        return PromptSession(
            history=FileHistory(str(self.history_file)),
            completer=ShellkitCompleter(self.runtime),
            style=Style.from_dict(styles),
            enable_history_search=True,
            complete_while_typing=True,
        )

    def prompt_message(self):
        if self.app.prompt is not None:
            return self.app.prompt(self.runtime)
        return default_prompt(self.runtime, self.remaining_time() if self._timeout_enabled else None)

    # -- session timeout --------------------------------------------------------------

    def reset_timeout(self) -> None:
        """Start the timeout over from now (after `set timeout N`, too)."""
        minutes = self.runtime.settings.get('timeout')
        self._deadline = time.monotonic() + minutes * 60
        self._arm_alarm()

    def remaining_time(self) -> str:
        """Remaining lifetime as MM:SS or H:MM:SS."""
        remaining = max(0, int(self._deadline - time.monotonic() + 0.999))
        hours, rem = divmod(remaining, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _expired(self) -> bool:
        return self._timeout_enabled and time.monotonic() >= self._deadline

    @staticmethod
    def _alarm_supported() -> bool:
        return os.name != 'nt' and hasattr(signal, 'SIGALRM')

    def _install_alarm(self) -> None:
        """SIGALRM ends the shell even while it sits waiting at the prompt."""
        if not self._alarm_supported():
            return
        try:
            self._previous_sigalrm = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, self._on_alarm)
            self._arm_alarm()
        except ValueError:
            # not the main thread: the deadline checks in the loop still work
            self._previous_sigalrm = None

    def _arm_alarm(self) -> None:
        if self._alarm_supported() and self._timeout_enabled:
            signal.alarm(max(1, int(self._deadline - time.monotonic())))

    def _clear_alarm(self) -> None:
        if not (self._alarm_supported() and self._timeout_enabled):
            return
        signal.alarm(0)
        if self._previous_sigalrm is not None:
            signal.signal(signal.SIGALRM, self._previous_sigalrm)
            self._previous_sigalrm = None

    def _on_alarm(self, _signum, _frame) -> None:
        # A running command is left to finish; the loop exits after it.
        self._timed_out = True
        self.runtime.running = False
        if self._at_prompt:
            raise SessionTimeout()

    # -- loop -----------------------------------------------------------------------

    def run(self) -> int:
        rt = self.runtime
        _show(rt, self.app.banner)

        try:
            while rt.running:
                if self._expired():
                    self._timed_out = True
                    break
                try:
                    self._at_prompt = True
                    try:
                        line = self.session.prompt(
                            self.prompt_message(),
                            refresh_interval=0.5 if self._timeout_enabled else None,
                        ).strip()
                    finally:
                        self._at_prompt = False
                    if line:
                        rt.execute_line(line)
                except SessionTimeout:
                    self._timed_out = True
                    break
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
        finally:
            self._clear_alarm()

        if self._timed_out:
            minutes = rt.settings.get('timeout')
            rt.console.print(f"[yellow]Session timeout reached after {minutes} "
                             f"minute{'s' if minutes != 1 else ''}. Exiting.[/yellow]")

        save_context_snapshot(rt)
        compact_history(self.history_file)
        _show(rt, self.app.goodbye)
        return rt.last_status if not self._timed_out else 0


def default_prompt(rt, remaining=None) -> HTML:
    """
    Two-line prompt:

        ╭─ ~/work/cases(ttl:14:59) [c:Case015 | n:24]
        ╰─❯
    """
    home = Path.home()
    try:
        if rt.cwd == home:
            where = '~'
        elif rt.cwd.is_relative_to(home):
            where = '~/' + str(rt.cwd.relative_to(home))
        else:
            where = str(rt.cwd)
    except (ValueError, RuntimeError):
        where = str(rt.cwd)

    level = rt.settings.get('prompt_level')
    if level:
        parts = where.strip('/').split('/')
        if len(parts) > level:
            where = '…/' + '/'.join(parts[-level:])

    head = f'<path>{html.escape(where)}</path>'
    if remaining is not None:
        head += f'<timeout>(ttl:{remaining})</timeout>'

    shown = []
    for key, entry in rt.context.items():
        label = key.label or key.name
        value = html.escape(key.display(entry))
        shown.append(f'<ctx-{key.name}>{html.escape(label)}:{value}</ctx-{key.name}>')
    if shown:
        head += ' <box>[</box>' + ' <sep>|</sep> '.join(shown) + '<box>]</box>'

    return HTML(f'<box>╭─</box> {head}\n<box>╰─❯</box> ')


def save_context_snapshot(rt) -> None:
    """
    Remember the context the session ended with, for `use last`.

    On exit rather than on every `use`, so what comes back is the state the
    session was left in. Nothing is written when the context is empty, so
    quitting a stray shell does not wipe a real one's snapshot.
    """
    tokens = rt.context.tokens()
    if tokens:
        rt.settings.data[LAST_CONTEXT_KEY] = tokens
        rt.settings.save()


def last_context_tokens(rt) -> List[str]:
    """The saved `use last` tokens, dropping any for keys no longer declared."""
    raw = rt.settings.data.get(LAST_CONTEXT_KEY, [])
    if isinstance(raw, str):
        raw = raw.split()
    if not isinstance(raw, list):
        return []
    tokens = []
    for token in raw:
        if isinstance(token, str) and ':' in token:
            name, value = token.split(':', 1)
            if name in rt.context.keys and value.strip():
                tokens.append(f"{name}:{value.strip()}")
    return tokens


# -- history ------------------------------------------------------------------------

def read_history(path: Path) -> List[str]:
    """History entries, newest first."""
    if not path.exists():
        return []
    return list(FileHistory(str(path)).load_history_strings())


def dedupe(entries: List[str]) -> List[str]:
    """Keep only the most recent copy of each entry (newest-first in and out)."""
    seen = set()
    unique = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return unique


def compact_history(path: Path) -> int:
    """
    Rewrite the history file without duplicates.

    Returns:
        Number of entries removed
    """
    try:
        entries = read_history(path)
        unique = dedupe(entries)
        removed = len(entries) - len(unique)
        if removed:
            stamp = datetime.now().isoformat(sep=' ', timespec='seconds')
            with open(path, 'w', encoding='utf-8') as f:
                # FileHistory keeps the oldest entry first on disk
                for entry in reversed(unique):
                    f.write(f"\n# {stamp}\n")
                    for line in entry.split('\n'):
                        f.write(f"+{line}\n")
        return removed
    except OSError:
        return 0


def _show(rt, what) -> None:
    if what is None:
        return
    if callable(what):
        what(rt)
    else:
        rt.console.print(what)

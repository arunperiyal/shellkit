"""
Runtime: the state of one session and the execution of command lines.

The runtime is the same whether the app runs a single command from the OS
shell or sits in the interactive shell; InteractiveShell only adds the prompt
loop on top. Commands receive the runtime as `ctx`.

A line goes through:

    alias expansion -> split on ';' -> for each part: split on '|'
      -> each segment is a builtin, a registered command, or (in a pipe,
         or with a leading '!') an external command run by the OS shell
"""

import io
import os
import shlex
import subprocess
import sys
import traceback
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.markup import escape

from shellkit.context import ContextStore, MissingContext, fill_context
from shellkit.parser import ParserExit, UsageError
from shellkit.settings import Settings
from shellkit.text import has_unquoted, split_unquoted, strip_ansi

# How long an external command in a pipe may run
PIPE_TIMEOUT_SECONDS = 30

# Status returned for a command name nothing recognises
STATUS_UNKNOWN = 127

_current: Optional['Runtime'] = None


def current_runtime() -> Optional['Runtime']:
    """
    The runtime of the running app, or None.

    For code deep in a call stack that has no ctx passed down to it. New code
    should take ctx from execute() instead.
    """
    return _current


class Runtime:
    """
    Session state plus line execution.

    Attributes:
        app: The App this runtime belongs to
        console: Rich console for normal output (captured inside pipes)
        err_console: Rich console on stderr for errors
        context: The ContextStore behind `use` / `unuse`
        settings: Settings behind `set`
        aliases: name -> expansion
        cwd: The shell's working directory
        running: Cleared by `exit` to end the interactive loop
        debug: Show tracebacks for errors in commands
    """

    def __init__(self, app, console: Optional[Console] = None,
                 err_console: Optional[Console] = None):
        global _current
        self.app = app
        self.console = console or Console()
        self.err_console = err_console or Console(stderr=True)
        self.storage = app.storage
        self.settings = Settings(self.storage, app.settings)
        self.context = ContextStore(app.contexts)
        self.aliases = self.storage.load_json(self.storage.ALIASES, {})
        self.cwd = Path.cwd()
        self.previous_cwd: Optional[Path] = None
        self.running = True
        self.debug = False
        self.interactive = False
        self.shell = None           # the InteractiveShell, when there is one
        self.last_status = 0
        self._capture_depth = 0

        self.parser = app.build_parser()
        self.builtins = app.builtin_table()
        _current = self

    # -- conveniences for commands -----------------------------------------------

    def get(self, key: str, default=None):
        """The value of context `key`, or `default` if it is not set."""
        return self.context.get(key, default)

    def out(self, text: str, end: str = '\n') -> None:
        """Write plain text: no markup, no highlighting, captured in pipes."""
        self.console.out(text, end=end, highlight=False)

    def error(self, message: str) -> None:
        """Report an error (rich markup allowed) on stderr."""
        self.err_console.print(f"[red]Error:[/red] {message}")

    def warn(self, message: str) -> None:
        self.err_console.print(f"[yellow]{message}[/yellow]")

    def confirm(self, question: str) -> bool:
        """Ask a y/N question. Anything but 'y' (including Ctrl+C) is no."""
        try:
            answer = self.console.input(f"{question} [dim](y/N)[/dim] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in ('y', 'yes')

    def resolve_path(self, path) -> Path:
        """A path typed by the user, made absolute against the shell's cwd."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.cwd / p

    def chdir(self, path) -> Path:
        """
        Change the shell's working directory (and the process's, so external
        commands see it too).

        Raises:
            NotADirectoryError / FileNotFoundError
        """
        target = self.resolve_path(path).resolve()
        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"Not a directory: {target}")
        os.chdir(target)
        self.previous_cwd, self.cwd = self.cwd, target
        return target

    def save_aliases(self) -> None:
        self.storage.save_json(self.storage.ALIASES, self.aliases)

    # -- output capture ------------------------------------------------------------

    @property
    def capturing(self) -> bool:
        return self._capture_depth > 0

    @contextmanager
    def capture(self):
        """
        Collect everything written to the console and to stdout.

        Yields a StringIO; its text has ANSI codes in it only if a command
        wrote them itself -- rich writes none to a non-terminal file.
        """
        buffer = io.StringIO()
        original = self.console.file
        self.console.file = buffer
        self._capture_depth += 1
        try:
            with redirect_stdout(buffer):
                yield buffer
        finally:
            self._capture_depth -= 1
            self.console.file = original

    def run_captured(self, line: str) -> str:
        """Run one segment and return its output as plain text."""
        with self.capture() as buffer:
            self.last_status = self.execute_segment(line)
        return strip_ansi(buffer.getvalue())

    # -- execution -----------------------------------------------------------------

    def expand_alias(self, line: str) -> str:
        """
        Expand an alias in the first word, repeatedly, so an alias may name
        another alias. An alias that leads back to itself stops expanding.
        """
        seen = set()
        while True:
            stripped = line.strip()
            first, _, rest = stripped.partition(' ')
            if first not in self.aliases or first in seen:
                return stripped
            seen.add(first)
            expansion = self.aliases[first]
            line = f"{expansion} {rest}".strip() if rest else expansion

    def execute_line(self, line: str) -> int:
        """
        Run a full line typed at the prompt: aliases, `;` chains and `|` pipes.

        Returns:
            Status of the last command run
        """
        status = 0
        for part in split_unquoted(line, ';'):
            if not part or not self.running:
                continue
            if has_unquoted(part, '|'):
                status = self.execute_pipe(part)
            else:
                status = self.execute_segment(part)
            self.last_status = status
        return status

    def execute_pipe(self, line: str) -> int:
        """
        Run `a | b | c`: each segment's output is the next one's input.

        Builtins and app commands do not read input, so only the first segment
        can be one; every later segment runs in the OS shell and gets the
        output on stdin. That makes `ls | grep plt` use the OS grep even
        though `grep` alone is the builtin.
        """
        segments = split_unquoted(line, '|')
        if any(not s for s in segments):
            self.error("empty command in pipe")
            return 2

        output: Optional[str] = None
        status = 0
        for i, segment in enumerate(segments):
            if i == 0 and self._is_internal(segment):
                output = self.run_captured(segment)
                status = self.last_status
            else:
                output, status = self._run_external_captured(segment, output)
                if status > 1:
                    # grep and friends return 1 for "no match"; >1 is a failure
                    break

        if output:
            self.console.out(output, end='', highlight=False)
        return status

    def execute_segment(self, line: str) -> int:
        """Run one command: no `;`, no `|`."""
        line = self.expand_alias(line)
        if not line:
            return 0
        if line.startswith('!'):
            return self._run_external(line[1:].strip())
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            self.error(escape(str(e)))
            return 2
        return self.execute_tokens(tokens)

    def execute_tokens(self, tokens: List[str]) -> int:
        """Run an already-split command: a builtin or a registered command."""
        if not tokens:
            return 0
        builtin = self.builtins.get(tokens[0])
        if builtin is not None:
            return self._run_builtin(builtin, tokens[1:])
        if tokens[0] in self.app.command_names():
            return self.run_command(tokens)
        self.error(f"Unknown command: {escape(tokens[0])}. "
                   f"Type [cyan]help[/cyan] to see available commands.")
        return STATUS_UNKNOWN

    def run_command(self, tokens: List[str]) -> int:
        """Parse `tokens` with the app parser and execute the command."""
        try:
            args = self.parser.parse_args(tokens)
        except UsageError as e:
            return self._report_usage_error(e, tokens)
        except ParserExit as e:
            return e.status

        command = self.app.command_for(args)
        try:
            used = fill_context(args, self.context)
        except MissingContext as e:
            self.error(f"no {e.key} given, and no context set "
                       f"(pass one, or [cyan]use {e.key}:VALUE[/cyan])")
            return 2

        if used and self.settings.get('echo_context'):
            for key, entry in used:
                self.console.print(f"[dim]Using {key}: {escape(entry.raw)}[/dim]")

        return self._guarded(lambda: command.run(args, self))

    # -- internals -------------------------------------------------------------------

    def _is_internal(self, segment: str) -> bool:
        segment = self.expand_alias(segment)
        if segment.startswith('!'):
            return False
        first = segment.split(maxsplit=1)[0] if segment else ''
        return first in self.builtins or first in self.app.command_names()

    def _run_builtin(self, builtin, argv: List[str]) -> int:
        if not builtin.own_help and argv in (['-h'], ['--help']):
            from shellkit.help import show_builtin_help
            show_builtin_help(self, builtin)
            return 0
        return self._guarded(lambda: builtin.handler(self, argv))

    def _guarded(self, fn) -> int:
        """Run a command body, turning exits and exceptions into a status."""
        try:
            result = fn()
        except SystemExit as e:
            code = e.code
            if code is None:
                return 0
            return code if isinstance(code, int) else 1
        except KeyboardInterrupt:
            self.err_console.print("[yellow]Interrupted[/yellow]")
            return 130
        except UsageError as e:
            # a command that parses further arguments itself
            return self._report_usage_error(e)
        except ParserExit as e:
            return e.status
        except Exception as e:
            self.error(escape(str(e)) or type(e).__name__)
            if self.debug:
                self.err_console.print(escape(traceback.format_exc()), style="dim")
            return 1
        if isinstance(result, bool):
            return 0 if result else 1
        return result if isinstance(result, int) else 0

    def _report_usage_error(self, e: UsageError, tokens: Optional[List[str]] = None) -> int:
        self.err_console.print(escape(e.parser.format_usage().rstrip()), style="dim")
        self.error(escape(str(e)))
        command = self.app.registry.get(tokens[0]) if tokens else None
        if command is not None and command.has_custom_help():
            self.err_console.print(f"[dim]`help {tokens[0]}` for details[/dim]")
        return 2

    def _run_external(self, command: str) -> int:
        """`!cmd`: hand the terminal to the OS shell (or capture, inside a pipe)."""
        if not command:
            return 0
        if self.capturing:
            output, status = self._run_external_captured(command, None)
            self.out(output, end='')
            return status
        try:
            return subprocess.run(command, shell=True, cwd=self.cwd).returncode
        except KeyboardInterrupt:
            return 130

    def _run_external_captured(self, command: str, input_text: Optional[str]):
        try:
            result = subprocess.run(
                command, shell=True, cwd=self.cwd, input=input_text,
                capture_output=True, text=True, timeout=PIPE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.error(f"'{escape(command)}' timed out after {PIPE_TIMEOUT_SECONDS} seconds")
            return '', 124
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.stdout, result.returncode

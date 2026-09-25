"""
App: what a program built on shellkit declares, and its entry point.

    app = App('flexflow', version=__version__, storage='~/.flexflow',
              contexts=[ContextKey('case', ...), ...],
              builtins=('core', 'files'), session_timeout=15)
    app.register(CaseCommand, DataCommand)
    sys.exit(app.run())

`app.run()` with command arguments runs that one command and exits; with none
it starts the interactive shell.
"""

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from shellkit.builtins import Builtin, load_bundle
from shellkit.context import ContextKey
from shellkit.parser import ShellkitParser, subparsers_action
from shellkit.registry import CommandRegistry
from shellkit.settings import Setting, non_negative_int, parse_bool
from shellkit.storage import Storage


class App:
    """
    A shellkit application.

    Parameters:
        name: Program name; the prompt and default storage dir derive from it
        version: Shown by --version and in the banner
        description: One line for the top-level --help
        storage: Directory for history/aliases/settings: '~/.name' (default)
                 or a relative path to keep them with the project
        contexts: ContextKeys the `use` builtin can set
        builtins: Bundles to include: 'core' and/or 'files'
        settings: App settings for `set`, beyond the framework's own
        banner: Printed when the shell starts: rich markup, or a callable(rt)
        goodbye: Printed when the shell ends, same forms as banner
        help_header: Printed at the top of `help`
        prompt: callable(rt) -> prompt_toolkit formatted text, replacing the
                default two-line prompt
        prompt_styles: Extra prompt_toolkit styles, merged over the defaults
        session_timeout: Minutes of shell lifetime before it exits by itself
                         (a `timeout` setting); None disables the feature
        oneshot: If True, `prog <command> ...` runs one command and exits.
                 If False the shell always starts and argv is ignored.
        parser_class: ArgumentParser subclass for the top-level parser
        file_style: callable(Path) -> rich style or None, colouring names in
                    ls and tree (e.g. data files magenta)
        setup: callable(runtime) -> state, run once when the runtime is
               created (shell or one-shot); the result is `rt.state`. Where
               an app opens its database or builds its managers, reading
               launch options from `rt.options`.
    """

    def __init__(self, name: str, *, version: Optional[str] = None,
                 description: str = '', storage=None,
                 contexts: Sequence[ContextKey] = (),
                 builtins: Sequence[str] = ('core',),
                 settings: Sequence[Setting] = (),
                 banner=None, goodbye=None, help_header: Optional[str] = None,
                 prompt: Optional[Callable] = None,
                 prompt_styles: Optional[Dict[str, str]] = None,
                 session_timeout: Optional[int] = None,
                 oneshot: bool = True,
                 parser_class=ShellkitParser,
                 file_style: Optional[Callable[[Path], Optional[str]]] = None,
                 setup: Optional[Callable] = None):
        self.name = name
        self.version = version
        self.description = description
        self.storage = Storage(storage or f'~/.{name}')
        self.contexts = list(contexts)
        self.registry = CommandRegistry()
        self.banner = banner
        self.goodbye = goodbye
        self.help_header = help_header
        self.prompt = prompt
        self.prompt_styles = dict(prompt_styles or {})
        self.session_timeout = session_timeout
        self.oneshot = oneshot
        self.parser_class = parser_class
        self.file_style = file_style
        self.setup = setup
        self._launch_options: List[tuple] = []

        self.settings: List[Setting] = [
            Setting('echo_context', True, parse_bool,
                    'Print "Using <key>: <value>" when a context fills an argument',
                    choices=('on', 'off')),
            Setting('prompt_level', 0, non_negative_int,
                    'Show only the last N path components in the prompt (0 = full path)'),
            Setting('debug', False, parse_bool,
                    'Show tracebacks when a command fails', choices=('on', 'off'),
                    on_change=lambda rt, value: setattr(rt, 'debug', value)),
        ]
        if session_timeout is not None:
            self.settings.append(Setting(
                'timeout', session_timeout, _positive_int,
                'Exit the shell after N minutes', choices=('15', '30', '60'),
                key='timeout_minutes',
                on_change=lambda rt, value: rt.shell and rt.shell.reset_timeout()))
        self.settings.extend(settings)

        self._builtins: List[Builtin] = []
        for bundle in builtins:
            self._builtins.extend(load_bundle(bundle))

        self._parser: Optional[argparse.ArgumentParser] = None
        self._command_parsers: Dict[str, argparse.ArgumentParser] = {}
        self._parser_owner: Dict[int, str] = {}

    # -- declaring ------------------------------------------------------------------

    def register(self, *commands) -> None:
        """Register command classes (or instances)."""
        for command in commands:
            self.registry.register(command)
        self._parser = None

    def add_builtin(self, builtin: Builtin) -> None:
        """Add a builtin; one with the same name replaces the bundled one."""
        self._builtins = [b for b in self._builtins if b.name != builtin.name]
        self._builtins.append(builtin)

    def builtin(self, name: str, help: str = '', **kwargs):
        """
        Decorator form of add_builtin:

            @app.builtin('web', help='Start/stop the web UI', usage='web start|stop')
            def web(rt, argv): ...
        """
        def decorate(handler):
            self.add_builtin(Builtin(name, handler, help=help, **kwargs))
            return handler
        return decorate

    def add_setting(self, setting: Setting) -> None:
        self.settings.append(setting)

    def launch_option(self, *flags, **kwargs) -> None:
        """
        An option given before the command (or before starting the shell),
        as for add_argument: `app.launch_option('--db', default='refs.db')`.
        The parsed values are `rt.options`.
        """
        self._launch_options.append((flags, kwargs))

    # -- lookup ---------------------------------------------------------------------

    def builtin_table(self) -> Dict[str, Builtin]:
        """name (and alias) -> Builtin."""
        table = {}
        for builtin in self._builtins:
            table[builtin.name] = builtin
            for alias in builtin.aliases:
                table[alias] = builtin
        return table

    def unique_builtins(self) -> List[Builtin]:
        return list(self._builtins)

    def build_parser(self) -> argparse.ArgumentParser:
        """The top-level parser: one subparser per registered command."""
        if self._parser is not None:
            return self._parser

        parser = self.parser_class(prog=self.name, description=self.description,
                                   add_help=False)
        subparsers = parser.add_subparsers(dest='command', metavar='<command>')
        self._command_parsers = {}
        self._parser_owner = {}
        for command in self.registry.all():
            sub = command.setup_parser(subparsers)
            if sub is None:
                sub = subparsers.choices.get(command.name)
            self._command_parsers[command.name] = sub
            self._parser_owner[id(sub)] = command.name

        self._parser = parser
        return parser

    def command_parser(self, name: str) -> Optional[argparse.ArgumentParser]:
        self.build_parser()
        return self._command_parsers.get(name)

    def command_names(self) -> Iterable[str]:
        """Command names, including argparse aliases given to add_parser."""
        action = subparsers_action(self.build_parser())
        return action.choices.keys() if action else ()

    def command_for(self, args):
        """The command object a parsed namespace belongs to."""
        action = subparsers_action(self.build_parser())
        sub = action.choices[args.command]
        return self.registry.get(self._parser_owner.get(id(sub), args.command))

    # -- running ----------------------------------------------------------------------

    def launch_parser(self) -> argparse.ArgumentParser:
        """Parser for what comes before the command: shellkit's flags plus the app's."""
        parser = ShellkitParser(prog=self.name, add_help=False)
        parser.add_argument('-d', '--debug', action='store_true', help='Show tracebacks')
        parser.add_argument('-V', '--version', action='store_true', help='Show the version')
        parser.add_argument('-h', '--help', action='store_true', help='Show the commands')
        for flags, kwargs in self._launch_options:
            parser.add_argument(*flags, **kwargs)
        parser.add_argument('command', nargs=argparse.REMAINDER)
        return parser

    def default_options(self) -> argparse.Namespace:
        """Launch options as if none were given (for a Runtime built directly)."""
        return self.launch_parser().parse_args([])

    def run(self, argv: Optional[List[str]] = None) -> int:
        """
        Entry point.

        Launch options come before any command: -V/--version, -h/--help,
        -d/--debug, and the app's own (launch_option()).

        Returns:
            Exit status
        """
        from shellkit.parser import ParserExit, UsageError
        from shellkit.runtime import Runtime

        argv = list(sys.argv[1:] if argv is None else argv)
        try:
            options = self.launch_parser().parse_args(argv)
        except UsageError as e:
            print(f"{self.name}: {e}", file=sys.stderr)
            return 2
        except ParserExit as e:
            return e.status

        if options.version:
            print(f"{self.name} {self.version or ''}".strip())
            return 0

        runtime = Runtime(self, options=options)
        runtime.debug = options.debug or runtime.settings.get('debug')

        if options.help:
            from shellkit.help import show_overview
            show_overview(runtime)
            return 0

        if options.command and self.oneshot:
            try:
                return runtime.execute_tokens(options.command)
            except KeyboardInterrupt:
                return 130

        from shellkit.shell import InteractiveShell
        return InteractiveShell(runtime).run()


def _positive_int(raw) -> int:
    value = int(raw)
    if value < 1:
        raise ValueError(f"expected a positive integer, got '{raw}'")
    return value

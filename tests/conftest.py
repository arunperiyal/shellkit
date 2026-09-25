import io

import pytest
from rich.console import Console

from shellkit import App, BaseCommand, ContextKey, Runtime, add_context_arg


class CaseCommand(BaseCommand):
    """Nested subcommands, a context positional and a context flag."""
    name = 'case'
    description = 'Case operations'
    category = 'Domain'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name, help=self.description)
        sub = p.add_subparsers(dest='case_cmd')
        show = sub.add_parser('show', help='Show a case')
        add_context_arg(show, 'case')
        show.add_argument('--format', choices=['table', 'json'], help='Output format')
        show.add_argument('--verbose', '-v', action='store_true', help='More detail')
        run = sub.add_parser('run', help='Run a case')
        add_context_arg(run, 'case')
        add_context_arg(run, 'node', '--node', type=int, required=False)
        run.add_argument('--to', help='Remote').completer = lambda rt, prefix: [
            ('alpha', 'remote one'), ('beta', 'remote two')]
        return p

    def execute(self, args, ctx):
        ctx.out(f"{args.case_cmd} case={args.case!r} node={getattr(args, 'node', None)!r}")
        return 0


class LegacyCommand(BaseCommand):
    """Written against the old execute(args) signature."""
    name = 'legacy'
    description = 'Old-style command'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name, help=self.description)
        p.add_argument('word')
        return p

    def execute(self, args):
        print(f"legacy {args.word}")
        return 3


class BoomCommand(BaseCommand):
    name = 'boom'
    description = 'Fails'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name)
        p.add_argument('--exit', type=int)
        return p

    def execute(self, args, ctx):
        if args.exit is not None:
            raise SystemExit(args.exit)
        raise RuntimeError('it broke')


def make_app(tmp_path, **kwargs):
    kwargs.setdefault('contexts', [
        ContextKey('case', description='Case directory', path=True, label='c'),
        ContextKey('node', parse=int, description='Node id', label='n'),
        ContextKey('time', parse=float, clears=('t1', 't2')),
        ContextKey('t1', parse=float, clears=('time',)),
        ContextKey('t2', parse=float, clears=('time',)),
    ])
    kwargs.setdefault('builtins', ('core', 'files'))
    app = App('testapp', storage=tmp_path / 'store', **kwargs)
    app.register(CaseCommand, LegacyCommand, BoomCommand)
    return app


class Harness:
    """A runtime whose console and error console write to buffers."""

    def __init__(self, app):
        self.out_buf = io.StringIO()
        self.err_buf = io.StringIO()
        self.rt = Runtime(
            app,
            console=Console(file=self.out_buf, width=200, color_system=None),
            err_console=Console(file=self.err_buf, width=200, color_system=None),
        )

    def run(self, line):
        """Run a line; return (status, stdout text, stderr text) for just this line."""
        self.out_buf.seek(0), self.out_buf.truncate()
        self.err_buf.seek(0), self.err_buf.truncate()
        status = self.rt.execute_line(line)
        return status, self.out_buf.getvalue(), self.err_buf.getvalue()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def app(tmp_path, workdir):
    return make_app(tmp_path)


@pytest.fixture
def sh(app):
    return Harness(app)

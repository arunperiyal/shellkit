"""`a | b` where a offers rows and b is a command: b runs once per row, the row's keys
set as context for that run."""

import pytest

from shellkit import BaseCommand
from tests.conftest import Harness, make_app


class RowsCommand(BaseCommand):
    """`rows time:1,2 [--none] [--text]`: offers one row per value."""
    name = 'rows'
    description = 'Offers rows'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name)
        p.add_argument('values', nargs='*')
        p.add_argument('--none', action='store_true')
        return p

    def execute(self, args, ctx):
        ctx.out('values: ' + ' '.join(args.values))
        ctx.emit([] if args.none else [{'case': args.values[0], 'time': v} for v in args.values[1:]])
        return 0


class SeeCommand(BaseCommand):
    """Prints the time and case it was run with, from the context."""
    name = 'see'
    description = 'Shows its context'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name)
        p.add_argument('--fail-at', type=float)
        return p

    def execute(self, args, ctx):
        ctx.out(f"see time={ctx.get('time')} case={ctx.get('case')}")
        return 3 if args.fail_at is not None and ctx.get('time') == args.fail_at else 0


@pytest.fixture
def sh(tmp_path, workdir):
    (workdir / 'C1').mkdir()
    app = make_app(tmp_path)
    app.register(RowsCommand, SeeCommand)
    return Harness(app)


def test_the_next_command_runs_once_per_row(sh):
    status, out, _ = sh.run('rows C1 10 20 | see')
    assert status == 0
    assert 'values: C1 10 20' in out                                  # the first one's output is shown
    assert out.count('see time=') == 2
    assert 'see time=10.0' in out and 'see time=20.0' in out
    assert 'case=C1' in out


def test_the_context_is_put_back_after_each_row(sh):
    sh.run('use node:7 time:99')
    sh.run('rows C1 10 20 | see')
    assert sh.rt.context.get('time') == 99.0 and sh.rt.context.get('node') == 7
    assert sh.rt.context.get('case') is None


def test_no_rows_is_said_and_nothing_runs(sh):
    status, out, err = sh.run('rows C1 --none | see')
    assert status == 1
    assert 'nothing to pass on' in err and 'see time' not in out


def test_one_failing_row_does_not_stop_the_rest_and_the_status_is_the_worst(sh):
    status, out, _ = sh.run('rows C1 10 20 30 | see --fail-at 20')
    assert status == 3
    assert out.count('see time=') == 3


def test_a_row_the_context_rejects_is_reported_and_skipped(sh):
    status, out, err = sh.run('rows C1 10 abc 30 | see')
    assert status == 2
    assert "Invalid time 'abc'" in err
    assert 'see time=10.0' in out and 'see time=30.0' in out and 'time=None' not in out


def test_a_shell_command_after_the_pipe_still_reads_the_text(sh):
    _, out, _ = sh.run('rows C1 10 20 | tr a-z A-Z')
    assert 'VALUES: C1 10 20' in out and 'see' not in out


def test_without_rows_a_command_after_the_pipe_is_the_shell_one_as_before(sh):
    status, out, err = sh.run('case show C1 | tr a-z A-Z')
    assert status == 0 and "SHOW CASE='C1'" in out


def test_rows_do_not_leak_into_the_next_line(sh):
    sh.run('rows C1 10')
    status, out, _ = sh.run('rows C1 10 | see')
    assert out.count('see time=') == 1

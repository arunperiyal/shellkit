"""A line ending in a backslash goes on at the next line, in the interactive shell."""

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from shellkit.shell import (continuation_bindings, continuation_prompt, continues,
                            join_continuations)


def test_a_trailing_backslash_continues_unless_it_is_escaped():
    assert continues('run a \\')
    assert continues('run a \\\\\\')            # three: the last one is not escaped
    assert not continues('run a')
    assert not continues('run a \\\\')          # two: an escaped backslash
    assert not continues('')


def test_continued_lines_join_as_in_bash():
    assert join_continuations('run post \\\n  --t1 5 \\\n--t2 9') == 'run post   --t1 5 --t2 9'
    assert join_continuations('one line') == 'one line'
    assert join_continuations('a \\\\\nb') == 'a \\\\\nb'     # escaped: the newline stays


def test_the_continuation_mark_sits_under_the_prompt():
    assert continuation_prompt(6, 1, 0) == '    … '
    assert continuation_prompt(1, 1, 0).strip() == '…'


def read(keys: str) -> str:
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        session = PromptSession(input=pipe, output=DummyOutput(),
                                key_bindings=continuation_bindings(),
                                prompt_continuation=continuation_prompt)
        return session.prompt('> ')


def test_enter_after_a_backslash_starts_the_next_line_instead_of_running():
    text = read('case show \\\rC1\r')
    assert text == 'case show \\\nC1'
    assert join_continuations(text) == 'case show C1'


def test_enter_runs_a_line_without_one_and_after_an_escaped_one():
    assert read('case show C1\r') == 'case show C1'
    assert read('echo \\\\\r') == 'echo \\\\'


def test_a_shell_session_is_built_with_the_binding(tmp_path, workdir):
    from tests.conftest import make_app, Harness
    from shellkit.shell import InteractiveShell
    shell = InteractiveShell(Harness(make_app(tmp_path)).rt)
    assert shell.session.prompt_continuation is continuation_prompt

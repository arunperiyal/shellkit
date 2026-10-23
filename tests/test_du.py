"""`du [-d N] [-s] [--dirs] [path]`: sizes of the entries of a directory down
to N levels (default 1), largest first within each level, with a total."""

import re

import pytest


@pytest.fixture
def tree(workdir):
    case = workdir / 'CS1'
    (case / 'RUN_1' / 'binary').mkdir(parents=True)
    (case / 'RUN_1' / 'binary' / 'riser.1000.plt').write_text('x' * 3000)
    (case / 'RUN_1' / 'riser.othd').write_text('x' * 500)
    (case / 'post').mkdir()
    (case / 'post' / 'a.png').write_text('x' * 100)
    (case / 'simflow.config').write_text('x' * 10)
    return case


def rows(sh, line):
    """(size, path) lines of `line` run in a pipe."""
    out = sh.rt.run_captured(line)
    assert sh.rt.last_status == 0
    return [tuple(re.split(r'\s+', l.strip(), maxsplit=1)) for l in out.splitlines()]


def test_default_depth_is_the_entries_of_the_directory(sh, tree):
    assert rows(sh, 'du CS1') == [('3.4KB', 'RUN_1/'), ('100.0B', 'post/'),
                                  ('10.0B', 'simflow.config'), ('3.5KB', '.')]


def test_depth_goes_down_the_tree_largest_first(sh, tree):
    assert [p for _, p in rows(sh, 'du -d 3 CS1')] == [
        'RUN_1/', 'RUN_1/binary/', 'RUN_1/binary/riser.1000.plt', 'RUN_1/riser.othd',
        'post/', 'post/a.png', 'simflow.config', '.']


@pytest.mark.parametrize('flags', ['-d2', '--depth 2', '--depth=2'])
def test_depth_spellings(sh, tree, flags):
    assert len(rows(sh, f'du {flags} CS1')) == 7


def test_dirs_only_and_summary(sh, tree):
    assert [p for _, p in rows(sh, 'du --dirs -d 2 CS1')] == \
        ['RUN_1/', 'RUN_1/binary/', 'post/', '.']
    assert rows(sh, 'du -s CS1') == [('3.5KB', '.')]
    assert rows(sh, 'du -d 0 CS1') == [('3.5KB', '.')]


def test_symlinks_are_not_followed(sh, tree):
    (tree / 'link').symlink_to(tree / 'RUN_1')
    sizes = dict((p, s) for s, p in rows(sh, 'du CS1'))
    assert 'link' in sizes and sizes['.'] != '6.9KB'


def test_table_indents_each_level_and_shows_the_total(sh, tree):
    status, out, _ = sh.run('du -d 2 CS1')
    assert status == 0
    assert '  binary/' in out and 'total' in out and '3.5KB' in out
    status, out, _ = sh.run('du -s CS1')
    assert status == 0 and out.split()[0] == '3.5KB'


@pytest.mark.parametrize('line, message', [
    ('du -d', '-d needs a value'), ('du -d x', 'whole number'), ('du -d -1', '0 or more'),
    ('du -x', 'unknown option -x'), ('du a b', 'usage: du'), ('du nope', 'not a directory'),
])
def test_bad_arguments(sh, tree, line, message):
    status, _, err = sh.run(line)
    assert status in (1, 2)
    assert message in err

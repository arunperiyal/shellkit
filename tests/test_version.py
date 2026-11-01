"""The `version` builtin: show (with updates from the upstream) and comments."""

import json
import os
import subprocess

import pytest

from tests.conftest import Harness, make_app

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def git(where, *args):
    return subprocess.run(['git', '-C', str(where), *args], check=True, env=GIT_ENV,
                          capture_output=True, text=True).stdout.strip()


def commit(where, name, message):
    (where / name).write_text(message)
    git(where, 'add', name)
    git(where, 'commit', '-q', '-m', message)


@pytest.fixture
def repos(tmp_path):
    """(checkout, other clone) of a bare origin with one commit."""
    origin = tmp_path / 'origin.git'
    git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(origin))
    seed = tmp_path / 'seed'
    git(tmp_path, 'clone', '-q', str(origin), str(seed))
    git(seed, 'checkout', '-q', '-b', 'main')
    commit(seed, 'a.txt', 'first')
    git(seed, 'push', '-q', 'origin', 'main')
    here = tmp_path / 'here'
    git(tmp_path, 'clone', '-q', str(origin), str(here))
    return here, seed


def harness(tmp_path, source=None):
    return Harness(make_app(tmp_path, version='1.2.0', source_dir=source))


def test_show_without_a_checkout(tmp_path, workdir):
    status, out, _ = harness(tmp_path).run('version')
    assert status == 0
    assert 'testapp 1.2.0' in out and 'shellkit' in out
    assert 'Update' not in out


def test_show_up_to_date(tmp_path, workdir, repos):
    here, _ = repos
    _, out, _ = harness(tmp_path, here).run('version show')
    assert 'branch' in out and 'main' in out and 'first' in out
    assert 'Up to date with origin/main' in out


def test_show_lists_new_upstream_commits_and_release(tmp_path, workdir, repos, monkeypatch):
    here, seed = repos
    monkeypatch.setattr(os, 'environ', GIT_ENV)
    commit(seed, 'b.txt', 'add plotting')
    commit(seed, 'c.txt', 'fix steady')
    git(seed, 'tag', 'v1.3.0')
    git(seed, 'push', '-q', '--tags', 'origin', 'main')

    _, out, _ = harness(tmp_path, here).run('version --offline')
    assert 'Up to date' in out                     # not fetched yet

    _, out, _ = harness(tmp_path, here).run('version show')
    assert 'Update available: 2 new commit(s) on origin/main' in out
    assert 'newest release v1.3.0' in out
    assert 'add plotting' in out and 'fix steady' in out
    assert git(here, 'rev-list', '--count', 'HEAD') == '1'     # nothing pulled


def test_show_reports_local_changes(tmp_path, workdir, repos):
    here, _ = repos
    (here / 'a.txt').write_text('edited')
    _, out, _ = harness(tmp_path, here).run('version --offline')
    assert '1 file(s) modified locally' in out


def test_comments_add_list_remove(tmp_path, workdir, repos):
    here, _ = repos
    h = harness(tmp_path, here)
    h.run('use case:CS1')
    status, out, _ = h.run('version comment data table should sort by time')
    assert status == 0 and 'Comment 1 saved' in out and '1.2.0' in out
    h.run('version comment second one')

    saved = json.loads((tmp_path / 'store' / 'comments.json').read_text())
    assert saved[0]['text'] == 'data table should sort by time'
    assert saved[0]['version'] == '1.2.0'
    assert saved[0]['commit'] == git(here, 'rev-parse', '--short', 'HEAD')
    assert saved[0]['context'] == ['case:CS1']

    _, out, _ = h.run('version comment')
    assert 'data table should sort by time' in out and 'second one' in out
    assert 'context: case:CS1' in out

    _, out, _ = h.run('version')
    assert '2 comment(s)' in out

    status, out, _ = h.run('version comment --remove 1')
    assert status == 0 and 'Removed 1' in out
    _, out, _ = h.run('version comment')
    assert 'sort by time' not in out and 'second one' in out
    status, _, err = h.run('version comment --remove 9')
    assert status == 1 and 'no comment 9' in err


def test_unknown_subcommand(tmp_path, workdir):
    status, _, err = harness(tmp_path).run('version update')
    assert status == 2 and 'unknown subcommand' in err


def test_a_branch_without_upstream_compares_with_the_remote_default(tmp_path, workdir, repos):
    here, seed = repos
    git(here, 'checkout', '-q', '-b', 'feature')
    commit(seed, 'b.txt', 'later on main')
    git(seed, 'push', '-q', 'origin', 'main')
    _, out, _ = harness(tmp_path, here).run('version')
    assert 'Update available: 1 new commit(s) on origin/' in out
    assert 'later on main' in out


def test_help_shows_the_brackets(tmp_path, workdir):
    _, out, _ = harness(tmp_path).run('version --help')
    assert 'version [show] [--offline]' in out

import json

from shellkit.shell import compact_history, default_prompt, save_context_snapshot
from tests.conftest import Harness, make_app


# -- use / unuse -----------------------------------------------------------------------

def test_use_list_shows_all_keys(sh):
    sh.run('use node:3')
    _, out, _ = sh.run('use list')
    assert 'case' in out and 'node' in out and '3' in out


def test_use_reports_bad_tokens(sh):
    status, _, err = sh.run('use node:abc case:X')
    assert status == 1
    assert 'Invalid node' in err
    assert sh.rt.get('case') == 'X'


def test_unuse(sh):
    sh.run('use case:A node:1')
    sh.run('unuse node')
    assert sh.rt.context.tokens() == ['case:A']
    sh.run('unuse')
    assert sh.rt.context.tokens() == []


def test_use_last_restores_snapshot(tmp_path, workdir):
    app = make_app(tmp_path)
    first = Harness(app)
    first.run('use case:A node:4')
    save_context_snapshot(first.rt)

    second = Harness(make_app(tmp_path))
    _, out, _ = second.run('use last')
    assert second.rt.context.tokens() == ['case:A', 'node:4']


def test_empty_context_does_not_overwrite_snapshot(tmp_path, workdir):
    h = Harness(make_app(tmp_path))
    h.run('use case:A')
    save_context_snapshot(h.rt)
    empty = Harness(make_app(tmp_path))
    save_context_snapshot(empty.rt)
    third = Harness(make_app(tmp_path))
    third.run('use last')
    assert third.rt.get('case') == 'A'


# -- set / alias / history -----------------------------------------------------------

def test_set_persists(tmp_path, workdir):
    h = Harness(make_app(tmp_path))
    status, out, _ = h.run('set prompt_level 2')
    assert status == 0
    data = json.loads((tmp_path / 'store' / 'settings.json').read_text())
    assert data['prompt_level'] == 2
    assert Harness(make_app(tmp_path)).rt.settings.get('prompt_level') == 2


def test_set_rejects_bad_value(sh):
    status, _, err = sh.run('set prompt_level -1')
    assert status == 2 and 'invalid value' in err


def test_timeout_setting_uses_legacy_key(tmp_path, workdir):
    h = Harness(make_app(tmp_path, session_timeout=15))
    assert h.rt.settings.get('timeout') == 15
    h.run('set timeout 20')
    data = json.loads((tmp_path / 'store' / 'settings.json').read_text())
    assert data['timeout_minutes'] == 20


def test_no_timeout_setting_without_session_timeout(sh):
    assert 'timeout' not in sh.rt.settings.specs


def test_alias_persists_and_unalias(tmp_path, workdir):
    h = Harness(make_app(tmp_path))
    h.run("alias ll='ls -l'")
    assert json.loads((tmp_path / 'store' / 'aliases').read_text()) == {'ll': 'ls -l'}
    h2 = Harness(make_app(tmp_path))
    assert h2.rt.aliases == {'ll': 'ls -l'}
    h2.run('unalias ll')
    assert Harness(make_app(tmp_path)).rt.aliases == {}


def test_history_dedupe(tmp_path):
    from prompt_toolkit.history import FileHistory
    path = tmp_path / 'history'
    history = FileHistory(str(path))
    for entry in ['a', 'b', 'a', 'c', 'a']:
        history.store_string(entry)
    assert compact_history(path) == 2
    assert list(FileHistory(str(path)).load_history_strings()) == ['a', 'c', 'b']


def test_help_overview_lists_commands_and_builtins(sh):
    _, out, _ = sh.run('help')
    assert 'Domain' in out and 'case' in out and 'Case operations' in out
    assert 'exit, quit, q' in out
    assert 'nano ' not in out     # hidden builtins are not listed


def test_help_for_command_uses_parser(sh):
    _, out, _ = sh.run('help case')
    assert 'usage: testapp case' in out


# -- files ------------------------------------------------------------------------------

def test_cd_pwd_and_back(sh, workdir):
    (workdir / 'sub').mkdir()
    sh.run('cd sub')
    assert sh.rt.cwd == workdir / 'sub'
    assert sh.run('pwd')[1].strip() == str(workdir / 'sub')
    sh.run('cd -')
    assert sh.rt.cwd == workdir
    status, _, err = sh.run('cd nowhere')
    assert status == 1 and 'not found' in err


def test_ls_flags_and_glob(sh, workdir):
    for name in ['RUN_10', 'RUN_2', '.hidden']:
        (workdir / name).write_text('')
    assert sh.run('ls -v | cat')[1].split() == ['RUN_2', 'RUN_10']
    assert '.hidden' in sh.run('ls -a | cat')[1]
    assert sh.run('ls RUN_1* | cat')[1].split() == ['RUN_10']
    assert sh.run('ls -z')[0] == 2


def test_cat_head_tail(sh, workdir):
    (workdir / 'f.txt').write_text(''.join(f"line{i}\n" for i in range(1, 31)))
    assert sh.run('cat f.txt')[1].count('\n') == 30
    assert sh.run('head -n 3 f.txt')[1] == 'line1\nline2\nline3\n'
    assert sh.run('tail -2 f.txt')[1] == 'line29\nline30\n'
    assert sh.run('cat f.txt | wc -l')[1].strip() == '30'


def test_markup_in_files_is_not_interpreted(sh, workdir):
    (workdir / 'm.txt').write_text('[red]not markup[/red]\n')
    assert sh.run('cat m.txt')[1] == '[red]not markup[/red]\n'


def test_grep(sh, workdir):
    (workdir / 'a.log').write_text('ok\nERROR one\nok\n')
    (workdir / 'b.log').write_text('error two\n')
    status, out, _ = sh.run('grep -i error *.log')
    assert status == 0 and 'ERROR one' in out and 'error two' in out
    assert sh.run('grep -l ERROR a.log b.log')[1] == 'a.log\n'
    assert sh.run('grep nothing a.log')[0] == 1


def test_cp_and_rm(sh, workdir):
    (workdir / 'src').mkdir()
    (workdir / 'src' / 'x.txt').write_text('x')
    assert sh.run('cp src copy')[0] == 1          # a directory needs -r
    assert sh.run('cp -r src copy')[0] == 0
    assert (workdir / 'copy' / 'x.txt').read_text() == 'x'
    assert sh.run('rm -f copy')[0] == 1           # a directory needs -r
    assert sh.run('rm -rf copy')[0] == 0
    assert not (workdir / 'copy').exists()


def test_tree(sh, workdir):
    (workdir / 'a' / 'b').mkdir(parents=True)
    out = sh.run('tree 2')[1]
    assert 'a/' in out and 'b/' in out


def test_file_style_hook(tmp_path, workdir):
    app = make_app(tmp_path, file_style=lambda p: 'magenta' if p.suffix == '.plt' else None)
    (workdir / 'x.plt').write_text('')
    h = Harness(app)
    assert 'x.plt' in h.run('ls')[1]


# -- prompt -----------------------------------------------------------------------------

def test_default_prompt_shows_context(sh):
    sh.run('use case:Case015 node:24')
    text = default_prompt(sh.rt, remaining='14:59').value
    assert 'c:Case015' in text and 'n:24' in text and 'ttl:14:59' in text


def test_prompt_level(sh, workdir):
    deep = workdir / 'a' / 'b' / 'c'
    deep.mkdir(parents=True)
    sh.run(f'cd {deep}')
    sh.run('set prompt_level 2')
    assert '…/b/c' in default_prompt(sh.rt).value

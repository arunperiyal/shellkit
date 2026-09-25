from tests.conftest import Harness, make_app


def test_command_runs_with_explicit_args(sh):
    status, out, err = sh.run('case show C1')
    assert status == 0
    assert "show case='C1' node=None" in out


def test_context_fills_and_is_echoed(sh):
    sh.run('use case:Case015 node:24')
    status, out, _ = sh.run('case run')
    assert status == 0
    assert 'Using case: Case015' in out
    assert "run case='Case015' node=24" in out


def test_echo_can_be_turned_off(sh):
    sh.run('set echo_context off')
    sh.run('use case:C1')
    _, out, _ = sh.run('case show')
    assert 'Using case' not in out


def test_missing_context_is_an_error(sh):
    status, _, err = sh.run('case show')
    assert status == 2
    assert 'no case given' in err


def test_usage_error_does_not_exit(sh):
    status, _, err = sh.run('case show C1 --format xml')
    assert status == 2
    assert 'invalid choice' in err
    assert 'usage: testapp case show' in err


def test_help_flag_does_not_exit(sh, capsys):
    status, _, _ = sh.run('case show --help')
    assert status == 0
    assert 'Output format' in capsys.readouterr().out


def test_unknown_command(sh):
    status, _, err = sh.run('frobnicate')
    assert status == 127
    assert 'Unknown command: frobnicate' in err


def test_legacy_execute_signature(sh, capsys):
    status, _, _ = sh.run('legacy hi')
    assert status == 3
    assert 'legacy hi' in capsys.readouterr().out


def test_exception_becomes_status_1(sh):
    status, _, err = sh.run('boom')
    assert status == 1
    assert 'it broke' in err
    assert 'Traceback' not in err


def test_debug_shows_traceback(sh):
    sh.run('set debug on')
    _, _, err = sh.run('boom')
    assert 'Traceback' in err


def test_system_exit_is_contained(sh):
    status, _, _ = sh.run('boom --exit 4')
    assert status == 4
    assert sh.rt.running


def test_semicolon_chaining(sh):
    status, out, _ = sh.run('use case:A; case show; case show B')
    assert "case='A'" in out and "case='B'" in out


def test_alias_expansion_and_recursion_guard(sh):
    sh.run("alias cs='case show'")
    sh.run("alias x=x")
    _, out, _ = sh.run('cs Z')
    assert "case='Z'" in out
    status, _, err = sh.run('x')
    assert status == 127


def test_alias_chains(sh):
    sh.run("alias a='b'")
    sh.run("alias b='case show'")
    _, out, _ = sh.run('a Q')
    assert "case='Q'" in out


def test_pipe_command_into_external(sh):
    status, out, _ = sh.run('case show C1 | tr a-z A-Z')
    assert status == 0
    assert "SHOW CASE='C1'" in out


def test_pipe_captures_plain_print(sh):
    _, out, _ = sh.run('legacy word | tr a-z A-Z')
    assert 'LEGACY WORD' in out


def test_pipe_builtin_into_external(sh, workdir):
    (workdir / 'a.plt').write_text('')
    (workdir / 'b.txt').write_text('')
    _, out, _ = sh.run('ls | grep plt')
    assert out.strip() == 'a.plt'


def test_bang_runs_os_command_in_cwd(sh, workdir, capfd):
    (workdir / 'marker').write_text('')
    status = sh.rt.execute_line('!ls')
    assert status == 0
    assert 'marker' in capfd.readouterr().out


def test_exit_stops_running(sh):
    sh.run('exit')
    assert not sh.rt.running


def test_oneshot_run(tmp_path, workdir, capsys):
    app = make_app(tmp_path)
    assert app.run(['legacy', 'once']) == 3
    assert 'legacy once' in capsys.readouterr().out


def test_version_flag(tmp_path, workdir, capsys):
    app = make_app(tmp_path, version='1.2')
    assert app.run(['--version']) == 0
    assert 'testapp 1.2' in capsys.readouterr().out


def test_registries_are_per_app(tmp_path, workdir):
    first = make_app(tmp_path)
    second = make_app(tmp_path)   # would raise "already registered" with a global registry
    assert first.registry is not second.registry


def test_current_runtime(sh):
    from shellkit import current_runtime
    assert current_runtime() is sh.rt


def test_app_builtin_decorator(tmp_path, workdir):
    app = make_app(tmp_path)

    @app.builtin('hello', help='Say hello', usage='hello [name]')
    def hello(rt, argv):
        rt.out(f"hello {' '.join(argv) or 'world'}")

    h = Harness(app)
    assert h.run('hello bob')[1] == 'hello bob\n'
    assert 'Say hello' in h.run('help hello')[1]
    assert 'hello [name]' in h.run('hello --help')[1]


def test_launch_option_and_setup_state(tmp_path, workdir, capsys):
    app = make_app(tmp_path, setup=lambda rt: {'db': rt.options.db})
    app.launch_option('--db', default='default.db')

    @app.builtin('whichdb')
    def whichdb(rt, argv):
        print(rt.state['db'])

    assert app.run(['--db', 'x.db', 'whichdb']) == 0
    assert capsys.readouterr().out == 'x.db\n'
    assert Harness(app).rt.state == {'db': 'default.db'}


def test_launch_options_stop_at_the_command(tmp_path, workdir, capsys):
    app = make_app(tmp_path)
    assert app.run(['-d', 'case', 'show', 'C1', '--verbose']) == 0
    assert "case='C1'" in capsys.readouterr().out


def test_unknown_launch_option(tmp_path, workdir, capsys):
    assert make_app(tmp_path).run(['--nope']) == 2
    assert 'unrecognized' in capsys.readouterr().err


def test_command_error_reports_without_traceback(tmp_path, workdir):
    from shellkit import CommandError
    app = make_app(tmp_path)

    @app.builtin('refuse')
    def refuse(rt, argv):
        raise CommandError('pass a key or --all')

    h = Harness(app)
    h.run('set debug on')
    status, _, err = h.run('refuse')
    assert status == 2
    assert 'Error: pass a key or --all' in err and 'Traceback' not in err

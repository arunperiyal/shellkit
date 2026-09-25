from shellkit.completion import complete


def texts(sh, line):
    return [c.text for c in complete(sh.rt, line)]


def test_first_word_offers_commands_builtins_aliases(sh):
    sh.run("alias cs='case show'")
    got = texts(sh, '')
    assert {'case', 'legacy', 'help', 'use', 'ls', 'cs'} <= set(got)
    assert texts(sh, 'ca') == ['case', 'cat']


def test_subcommands_with_help(sh):
    cands = complete(sh.rt, 'case ')
    assert [c.text for c in cands] == ['show', 'run']
    assert cands[0].meta == 'Show a case'


def test_flags_of_nested_parser(sh):
    got = texts(sh, 'case show --')
    assert '--format' in got and '--verbose' in got


def test_used_flag_not_offered_again(sh):
    assert '--verbose' not in texts(sh, 'case show C1 -v --')


def test_choices_after_flag(sh):
    assert texts(sh, 'case show C1 --format ') == ['table', 'json']
    assert texts(sh, 'case show C1 --format j') == ['json']


def test_argument_completer(sh):
    assert texts(sh, 'case run --to ') == ['alpha', 'beta']


def test_context_positional_uses_context_completion(sh, workdir):
    (workdir / 'Case001').mkdir()
    (workdir / 'Case002').mkdir()
    (workdir / 'other.txt').write_text('')
    assert texts(sh, 'case show Ca') == ['Case001/', 'Case002/']


def test_nested_path_completion_replaces_whole_word(sh, workdir):
    (workdir / 'runs' / 'RUN_1').mkdir(parents=True)
    [cand] = complete(sh.rt, 'cat runs/R')
    assert cand.text == 'runs/RUN_1/' and cand.replace == len('runs/R')
    assert cand.display == 'RUN_1/'


def test_completion_after_pipe_and_semicolon(sh):
    assert texts(sh, 'use case:x; case s') == ['show']
    assert texts(sh, 'case show | leg') == ['legacy']


def test_alias_expanded_for_completion(sh):
    sh.run("alias c='case'")
    assert texts(sh, 'c ') == ['show', 'run']


def test_use_completion(sh):
    got = texts(sh, 'use ')
    assert got[:2] == ['list', 'last']
    assert 'case:' in got and 'node:' in got
    assert 'case:' not in texts(sh, 'use case:A ')


def test_use_value_completion(sh, workdir):
    (workdir / 'Case9').mkdir()
    assert texts(sh, 'use case:C') == ['case:Case9/']


def test_unuse_and_set_completion(sh):
    assert 'all' in texts(sh, 'unuse ')
    assert 'echo_context' in texts(sh, 'set ')
    assert texts(sh, 'set debug ') == ['on', 'off']


def test_unterminated_quote_does_not_crash(sh):
    assert texts(sh, 'case show "abc') == []

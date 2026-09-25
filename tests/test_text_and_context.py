import argparse

import pytest

from shellkit.context import (ContextError, ContextKey, ContextStore, MissingContext,
                              add_context_arg, explicit, fill_context)
from shellkit.text import has_unquoted, split_unquoted, strip_ansi


@pytest.mark.parametrize('line, sep, expected', [
    ('a; b; c', ';', ['a', 'b', 'c']),
    ('plot --title "A; B"; x', ';', ['plot --title "A; B"', 'x']),
    ("echo 'a|b' | grep a", '|', ["echo 'a|b'", 'grep a']),
    (r'echo a\;b', ';', [r'echo a\;b']),
    ('a;;b', ';', ['a', '', 'b']),
])
def test_split_unquoted(line, sep, expected):
    assert split_unquoted(line, sep) == expected


def test_has_unquoted():
    assert has_unquoted('a | b', '|')
    assert not has_unquoted('echo "a | b"', '|')


def test_strip_ansi():
    assert strip_ansi('\x1b[31mred\x1b[0m plain') == 'red plain'


def store():
    return ContextStore([
        ContextKey('case'),
        ContextKey('node', parse=int),
        ContextKey('time', parse=float, clears=('t1',)),
        ContextKey('t1', parse=float, clears=('time',)),
        ContextKey('upper', parse=lambda raw, rt: f"{raw.upper()}@{rt}"),
    ])


def test_set_parses_and_keeps_raw():
    s = store()
    assert s.set('node', ' 24 ') == 24
    assert s.get('node') == 24
    assert s.raw('node') == '24'
    assert s.tokens() == ['node:24']


def test_parse_can_take_runtime():
    s = store()
    assert s.set('upper', 'x', runtime='RT') == 'X@RT'


def test_clears_mutually_exclusive_keys():
    s = store()
    s.set('t1', '1.5')
    s.set('time', '3')
    assert not s.is_set('t1') and s.get('time') == 3.0
    s.set('t1', '2')
    assert not s.is_set('time')


def test_bad_values_raise_context_error():
    s = store()
    with pytest.raises(ContextError, match='Unknown context'):
        s.set('nope', '1')
    with pytest.raises(ContextError, match='Invalid node'):
        s.set('node', 'abc')
    with pytest.raises(ContextError, match='Missing value'):
        s.set('case', '  ')


def test_apply_tokens_keeps_going_after_errors():
    s = store()
    applied, errors = s.apply_tokens(['case:C1', 'node:x', 'bogus', 'NODE:5'])
    assert applied == ['case:C1', 'node:5']
    assert len(errors) == 2
    assert s.tokens() == ['case:C1', 'node:5']


def test_tokens_follow_declaration_order():
    s = store()
    s.apply_tokens(['node:1', 'case:C'])
    assert s.tokens() == ['case:C', 'node:1']


def make_parser():
    p = argparse.ArgumentParser()
    add_context_arg(p, 'case')
    add_context_arg(p, 'node', '--node', type=int, required=False)
    return p


def test_context_arg_filled_when_omitted():
    s = store()
    s.set('case', 'C1')
    s.set('node', '7')
    args = make_parser().parse_args([])
    used = fill_context(args, s)
    assert (args.case, args.node) == ('C1', 7)
    assert [k for k, _ in used] == ['case', 'node']


def test_explicit_argument_wins():
    s = store()
    s.set('case', 'C1')
    args = make_parser().parse_args(['C9', '--node', '3'])
    fill_context(args, s)
    assert (args.case, args.node) == ('C9', 3)


def test_missing_required_context():
    args = make_parser().parse_args([])
    with pytest.raises(MissingContext) as info:
        fill_context(args, store())
    assert info.value.key == 'case'


def test_missing_optional_context_is_none():
    s = store()
    s.set('case', 'C1')
    args = make_parser().parse_args([])
    fill_context(args, s)
    assert args.node is None


def window_parser():
    """--t1/--t2 where a single `time` fills both, but only if neither is given."""
    def end(name):
        def resolve(store, ns):
            if store.is_set(name):
                return store.get(name)
            if store.is_set('time') and not explicit(ns, 't1') and not explicit(ns, 't2'):
                return store.get('time')
            return None
        return resolve

    p = argparse.ArgumentParser()
    add_context_arg(p, 't1', '--t1', type=float, required=False, resolve=end('t1'))
    add_context_arg(p, 't2', '--t2', type=float, required=False, resolve=end('t2'))
    add_context_arg(p, 'node', '--node', type=int, required=False, default=-1)
    return p


def test_resolve_derives_values():
    s = store()
    s.set('time', '7')
    args = window_parser().parse_args([])
    used = fill_context(args, s)
    assert (args.t1, args.t2) == (7.0, 7.0)
    assert used == [('t1', '7.0'), ('t2', '7.0')]


def test_resolve_sees_what_the_user_typed():
    s = store()
    s.set('time', '7')
    args = window_parser().parse_args(['--t1', '2'])
    fill_context(args, s)
    assert (args.t1, args.t2) == (2.0, None)


def test_fallback_default_when_context_gives_nothing():
    args = window_parser().parse_args([])
    fill_context(args, store())
    assert args.node == -1


def test_type_applies_to_context_values():
    s = store()
    s.set('node', '5')
    p = argparse.ArgumentParser()
    add_context_arg(p, 'node', '--node', type=str, required=False)
    add_context_arg(p, 't1', '--t1', type=int, required=False)
    s.set('t1', '2.5')
    with pytest.raises(ContextError, match='does not fit'):
        fill_context(p.parse_args([]), s)
    args = p.parse_args(['--t1', '1'])
    fill_context(args, s)
    assert args.node == '5'

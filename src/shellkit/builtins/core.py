"""
Core builtins: exit, help, clear, history, alias, unalias, use, unuse, set.
"""

import re

from rich import box
from rich.markup import escape
from rich.table import Table

from shellkit.builtins import Builtin
from shellkit.completion import context_values


def builtins():
    return [
        Builtin('exit', _exit, help='Exit the shell', aliases=('quit', 'q')),
        Builtin('help', _help, help='Show commands, or help for one',
                usage='help [command]', aliases=('?',), complete=_complete_help),
        Builtin('clear', _clear, help='Clear the screen'),
        Builtin('history', _history, help='Show command history',
                usage='history [--unique] [N]',
                details="  [cyan]-u, --unique[/cyan]   Only the latest copy of each command\n"
                        "  [cyan]N[/cyan]              How many to show (default: 20)",
                complete=lambda rt, args, cur: [('--unique', 'Latest copy of each command')]),
        Builtin('alias', _alias, help='Define or list aliases',
                usage="alias [name[=value]]",
                details="  alias                 list all aliases\n"
                        "  alias ll               show one\n"
                        "  alias ll='ls -l'       define one (kept across sessions)",
                complete=_complete_alias_names),
        Builtin('unalias', _unalias, help='Remove aliases', usage='unalias <name> [name ...]',
                complete=_complete_alias_names),
        Builtin('use', _use, help='Set context used by commands',
                usage='use name:value [name:value ...] | use list | use last',
                complete=_complete_use, category='Context', own_help=True),
        Builtin('unuse', _unuse, help='Clear context', usage='unuse [name ...|all]',
                complete=_complete_unuse, category='Context', own_help=True),
        Builtin('set', _set, help='Show or change program settings',
                usage='set [name [value]]', complete=_complete_set),
    ]


# -- exit / help / clear ---------------------------------------------------------------

def _exit(rt, argv):
    rt.running = False
    return 0


def _help(rt, argv):
    from shellkit.help import show_overview, show_topic
    if not argv:
        show_overview(rt)
        return 0
    return show_topic(rt, argv[0])


def _complete_help(rt, args, current):
    if args:
        return []
    names = [(c.name, c.description) for c in rt.app.registry.all()]
    names += [(b.name, b.help) for b in rt.app.unique_builtins()]
    return names


def _clear(rt, argv):
    rt.console.clear()
    return 0


# -- history ------------------------------------------------------------------------

def _history(rt, argv):
    from shellkit.shell import dedupe, read_history

    unique = False
    count = 20
    for arg in argv:
        if arg in ('-u', '--unique'):
            unique = True
        elif arg.isdigit():
            count = int(arg)
        else:
            rt.error(f"history: unknown argument '{escape(arg)}' (history [--unique] [N])")
            return 2

    entries = read_history(rt.storage.path(rt.storage.HISTORY))
    if not entries:
        rt.console.print("[dim]No command history yet.[/dim]")
        return 0
    shown = dedupe(entries) if unique else entries

    # oldest of the selection first, numbered so the newest is 1
    selection = shown[:count]
    for i, entry in reversed(list(enumerate(selection, 1))):
        rt.console.print(f"  [dim]{i:3d}[/dim]  {escape(entry.replace(chr(10), ' ; '))}")
    if len(shown) > count:
        rt.console.print(f"[dim]... most recent {count} of {len(shown)}[/dim]")
    return 0


# -- aliases -----------------------------------------------------------------------

def _alias(rt, argv):
    if not argv:
        if not rt.aliases:
            rt.console.print("[dim]No aliases defined[/dim]")
        for name, value in sorted(rt.aliases.items()):
            rt.console.print(f"alias [cyan]{name}[/cyan]=[yellow]'{escape(value)}'[/yellow]")
        return 0

    status = 0
    for arg in argv:
        match = re.match(r'^([\w.-]+)=(.*)$', arg, re.S)
        if match:
            name, value = match.group(1), match.group(2).strip()
            if not value:
                rt.error(f"alias: empty value for '{name}'")
                status = 1
                continue
            if name in rt.builtins and rt.builtins[name].name in ('alias', 'unalias'):
                rt.error(f"alias: cannot redefine '{name}'")
                status = 1
                continue
            rt.aliases[name] = value
            rt.save_aliases()
            rt.console.print(f"[green]alias[/green] [cyan]{name}[/cyan]=[yellow]'{escape(value)}'[/yellow]")
        elif arg in rt.aliases:
            rt.console.print(f"alias [cyan]{arg}[/cyan]=[yellow]'{escape(rt.aliases[arg])}'[/yellow]")
        else:
            rt.warn(f"alias: {arg}: not found")
            status = 1
    return status


def _unalias(rt, argv):
    if not argv:
        rt.error("usage: unalias <name> [name ...]")
        return 2
    status = 0
    for name in argv:
        if rt.aliases.pop(name, None) is not None:
            rt.console.print(f"[green]Removed alias:[/green] {name}")
        else:
            rt.warn(f"unalias: {name}: not found")
            status = 1
    rt.save_aliases()
    return status


def _complete_alias_names(rt, args, current):
    return [(name, value) for name, value in rt.aliases.items()]


# -- context -------------------------------------------------------------------------

def _use(rt, argv):
    from shellkit.shell import last_context_tokens

    store = rt.context
    if not store.keys:
        rt.warn("This program declares no contexts.")
        return 1
    if not argv or argv[0] in ('-h', '--help', 'help'):
        _use_help(rt)
        return 0

    if argv[0] == 'list':
        _use_list(rt)
        return 0

    if argv[0] == 'last':
        tokens = last_context_tokens(rt)
        if not tokens:
            rt.console.print("[dim]No saved context. One is written when a shell "
                             "with a context set exits.[/dim]")
            return 0
        rt.console.print(f"[dim]Restoring the context of the last session: "
                         f"{escape(' '.join(tokens))}[/dim]")
        argv = tokens

    applied, errors = store.apply_tokens(argv, rt)
    for message in errors:
        rt.warn(message)
    for token in applied:
        name, _ = token.split(':', 1)
        key = store.keys[name]
        rt.console.print(f"[green]✓[/green] {name}: [cyan]{escape(key.display(store.entry(name)))}[/cyan]")
    return 1 if errors else 0


def _use_list(rt):
    from shellkit.shell import last_context_tokens

    store = rt.context
    table = Table(box=box.SIMPLE, header_style="bold yellow")
    table.add_column("Context", style="cyan")
    table.add_column("Value")
    table.add_column("", style="dim")
    for name, key in store.keys.items():
        entry = store.entry(name)
        value = escape(key.display(entry)) if entry else "[dim]-[/dim]"
        table.add_row(name, value, escape(key.description))
    rt.console.print(table)

    live = dict(t.split(':', 1) for t in store.tokens())
    saved = dict(t.split(':', 1) for t in last_context_tokens(rt))
    if not live:
        rt.console.print("[dim]Nothing set. `use name:value` to set one.[/dim]")
    if saved and saved != live:
        differs = ' '.join(f"{k}:{v}" for k, v in saved.items() if live.get(k) != v)
        rt.console.print(f"[dim]`use last` would set: {escape(differs)}[/dim]")


def _use_help(rt):
    console = rt.console
    console.print()
    console.print("[bold cyan]use[/bold cyan]  Set context that commands pick up")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  use name:value [name:value ...]")
    console.print("  use list        [dim]# what is set, and what else can be[/dim]")
    console.print("  use last        [dim]# the context the last session ended with[/dim]")
    console.print()
    console.print("[bold]CONTEXTS:[/bold]")
    width = max(len(n) for n in rt.context.keys)
    for name, key in rt.context.keys.items():
        console.print(f"  [cyan]{name:<{width}}[/cyan]  {escape(key.description)}")
    console.print()


def _complete_use(rt, args, current):
    store = rt.context
    options = []
    if not args:
        options += [('list', 'Show every context, set or not'),
                    ('last', 'Restore the context the last session ended with')]
    elif args[0] in ('list', 'last'):
        return []

    if ':' in current:
        name, partial = current.split(':', 1)
        key = store.keys.get(name)
        if key is None:
            return []
        for option in context_values(rt, key, partial):
            if isinstance(option, (tuple, list)):
                value, meta = option[0], option[1] if len(option) > 1 else name
            else:
                value, meta = option, name
            options.append((f"{name}:{value}", meta))
        return options

    used = {a.split(':', 1)[0] for a in args if ':' in a}
    options += [(f"{name}:", key.description) for name, key in store.keys.items()
                if name not in used]
    return options


def _unuse(rt, argv):
    store = rt.context
    if argv and argv[0] in ('-h', '--help', 'help'):
        rt.console.print(f"[bold]USAGE:[/bold] unuse [name ...|all]  "
                         f"[dim]names: {', '.join(store.keys)}[/dim]")
        return 0
    if not argv or argv == ['all']:
        store.clear_all()
        rt.console.print("[green]✓[/green] All contexts cleared")
        return 0
    status = 0
    for name in argv:
        if name not in store.keys:
            rt.warn(f"Unknown context: {name} (valid: {', '.join(store.keys)}, all)")
            status = 1
        elif store.clear(name):
            rt.console.print(f"[green]✓[/green] {name} cleared")
        else:
            rt.console.print(f"[dim]{name} was not set[/dim]")
    return status


def _complete_unuse(rt, args, current):
    options = [(name, f"{rt.context.raw(name) or '(not set)'}")
               for name in rt.context.keys if name not in args]
    if not args:
        options.append(('all', 'Clear every context'))
    return options


# -- settings -------------------------------------------------------------------------

def _set(rt, argv):
    settings = rt.settings
    if not argv:
        table = Table(box=box.SIMPLE, header_style="bold yellow")
        table.add_column("Setting", style="cyan")
        table.add_column("Value")
        table.add_column("", style="dim")
        for name, spec in settings.specs.items():
            table.add_row(name, escape(_show_value(settings.get(name))), escape(spec.help))
        rt.console.print(table)
        rt.console.print(f"[dim]`set <name> <value>` to change; kept in "
                         f"{rt.storage.path(rt.storage.SETTINGS)}[/dim]")
        return 0

    name = argv[0]
    spec = settings.specs.get(name)
    if spec is None:
        rt.error(f"Unknown setting: {escape(name)} (available: {', '.join(settings.specs)})")
        return 2
    if len(argv) == 1:
        rt.console.print(f"{name}: [cyan]{escape(_show_value(settings.get(name)))}[/cyan]")
        return 0
    if len(argv) > 2:
        rt.error(f"usage: set {name} <value>")
        return 2

    try:
        value = settings.set(name, argv[1])
    except (TypeError, ValueError) as e:
        rt.error(f"invalid value for {name}: {escape(str(e))}")
        return 2
    if spec.on_change is not None:
        spec.on_change(rt, value)
    rt.console.print(f"[green]✓[/green] {name} = [cyan]{escape(_show_value(value))}[/cyan]")
    return 0


def _show_value(value) -> str:
    if isinstance(value, bool):
        return 'on' if value else 'off'
    return str(value)


def _complete_set(rt, args, current):
    specs = rt.settings.specs
    if not args:
        return [(name, spec.help) for name, spec in specs.items()]
    spec = specs.get(args[0])
    if spec is None or len(args) > 1:
        return []
    return list(spec.choices)

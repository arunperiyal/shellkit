"""
`help` output, built from the registry and the builtin table.
"""

from rich import box
from rich.markup import escape
from rich.table import Table


def show_overview(rt) -> None:
    """`help` with no argument: commands by category, then builtins."""
    app = rt.app
    console = rt.console

    console.print()
    if app.help_header:
        console.print(app.help_header)
        console.print()

    for category, commands in app.registry.by_category().items():
        table = _table(category)
        for cmd in commands:
            table.add_row(cmd.name, escape(cmd.description))
        console.print(table)

    by_category = {}
    for builtin in app.unique_builtins():
        if builtin.hidden:
            continue
        by_category.setdefault(builtin.category, []).append(builtin)
    for category, builtins in by_category.items():
        table = _table(category)
        for builtin in builtins:
            names = ', '.join([builtin.name, *builtin.aliases])
            table.add_row(names, escape(builtin.help))
        console.print(table)

    console.print("[dim]`help <command>` or `<command> --help` for details. "
                  "Chain with `;`, pipe with `|`, run an OS command with `!cmd`.[/dim]")
    console.print()


def show_topic(rt, name: str) -> int:
    """`help <name>`: a command's help or a builtin's."""
    builtin = rt.builtins.get(name)
    if builtin is not None:
        show_builtin_help(rt, builtin)
        return 0

    command = rt.app.registry.get(name)
    if command is None:
        rt.error(f"No help for '{escape(name)}': not a command or builtin")
        return 1
    if command.has_custom_help():
        command.show_help()
        return 0
    parser = rt.app.command_parser(name)
    if parser is not None:
        rt.out(parser.format_help().rstrip())
    else:
        rt.console.print(f"[cyan]{name}[/cyan]  {escape(command.description)}")
    return 0


def show_builtin_help(rt, builtin) -> None:
    console = rt.console
    console.print()
    console.print(f"[bold cyan]{builtin.name}[/bold cyan]  {escape(builtin.help)}")
    if builtin.usage:
        console.print()
        console.print(f"[bold]USAGE:[/bold] {escape(builtin.usage)}")
    if builtin.aliases:
        console.print(f"[bold]ALSO:[/bold]  {', '.join(builtin.aliases)}")
    if builtin.details:
        console.print()
        console.print(builtin.details)
    console.print()


def _table(title: str) -> Table:
    table = Table(title=f"[bold yellow]{escape(title)}[/bold yellow]", title_justify='left',
                  box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    return table

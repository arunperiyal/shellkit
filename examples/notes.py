#!/usr/bin/env python3
"""
A tiny shellkit app: notes kept as text files in a folder.

    python examples/notes.py              # interactive shell
    python examples/notes.py list         # one command, then exit

Inside the shell:
    use book:work
    add "call the lab"        # goes into the `work` book
    list | grep lab
"""

import sys
from pathlib import Path

from shellkit import App, BaseCommand, ContextKey, add_context_arg, paths

NOTES = Path.home() / '.notes-demo'


def books(rt, prefix):
    return [p.name for p in NOTES.iterdir() if p.is_dir()] if NOTES.exists() else []


class AddCommand(BaseCommand):
    name = 'add'
    description = 'Add a note to a book'
    category = 'Notes'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name, help=self.description)
        p.add_argument('text', help='The note')
        add_context_arg(p, 'book', '--book', '-b')
        return p

    def execute(self, args, ctx):
        book = NOTES / args.book
        book.mkdir(parents=True, exist_ok=True)
        with open(book / 'notes.txt', 'a') as f:
            f.write(args.text + '\n')
        ctx.console.print(f"[green]✓[/green] added to [cyan]{args.book}[/cyan]")


class ListCommand(BaseCommand):
    name = 'list'
    description = 'List notes in a book (or every book)'
    category = 'Notes'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name, help=self.description)
        add_context_arg(p, 'book', required=False)
        p.add_argument('--export', help='Also write them to a file').completer = paths(('.txt',))
        return p

    def execute(self, args, ctx):
        chosen = [NOTES / args.book] if args.book else sorted(NOTES.glob('*'))
        for book in chosen:
            notes = book / 'notes.txt'
            if notes.exists():
                for line in notes.read_text().splitlines():
                    ctx.out(f"{book.name}: {line}")


app = App(
    'notes', version='0.1', description='Notes demo for shellkit',
    contexts=[ContextKey('book', description='Notebook to use', complete=books,
                         label='b', style='#00aaff bold')],
    builtins=('core', 'files'),
    banner="[bold cyan]notes[/bold cyan] -- a shellkit demo. [dim]help, Tab, exit[/dim]\n",
    session_timeout=30,
)
app.register(AddCommand, ListCommand)

if __name__ == '__main__':
    sys.exit(app.run())

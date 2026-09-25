# shellkit

Framework for prompt-based CLI programs: argparse commands in a registry, and
an interactive shell with context (`use`), aliases, `;` chaining, `|` pipes,
history, settings and completion generated from the parsers.

## Install

```bash
pip install -e /media/arunperiyal/Works/projects/shellkit        # in the app's environment
pip install -e '/media/arunperiyal/Works/projects/shellkit[dev]' # plus pytest
```

## Example

```python
from shellkit import App, BaseCommand, ContextKey, add_context_arg

class ShowCommand(BaseCommand):
    name = 'show'
    description = 'Show a case'

    def setup_parser(self, subparsers):
        p = subparsers.add_parser(self.name, help=self.description)
        add_context_arg(p, 'case')            # optional if `use case:X` is set
        return p

    def execute(self, args, ctx):
        ctx.console.print(f"case: {args.case}")

app = App('demo', contexts=[ContextKey('case', path=True)], builtins=('core', 'files'))
app.register(ShowCommand)
app.run()
```

```
╭─ ~/work [case:C1]
╰─❯ use case:C1; show | tr a-z A-Z
```

A fuller example is in `examples/notes.py`. `DESIGN.md` explains how the
pieces fit together and the plan for moving flexflow_manager and
reference_manager onto shellkit.

## Tests

```bash
python -m pytest
```

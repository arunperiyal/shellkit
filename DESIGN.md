# shellkit design

Framework for prompt-based CLI programs, extracted from flexflow_manager's
`src/cli/` so flexflow_manager, reference_manager and later tools share one
shell instead of each carrying their own.

## Goal

A pip-installable package that owns the interactive shell and command
plumbing. Each app keeps only its commands, context keys and domain code.

## Layout

```
src/shellkit/
  app.py          App: declares commands/contexts/builtins/settings; run()
  command.py      BaseCommand (flexflow's commands/base.py + ctx)
  registry.py     CommandRegistry, one per App (no module global)
  parser.py       ShellkitParser: argparse that raises instead of exiting
  context.py      ContextKey, ContextStore, add_context_arg, fill_context
  runtime.py      Runtime: session state + line execution (; | ! aliases)
  shell.py        InteractiveShell: prompt loop, history, prompt, timeout
  completion.py   completer generated from the argparse tree
  help.py         `help` built from the registry and builtins
  settings.py     Setting / Settings behind `set`
  storage.py      per-app dir: history, aliases, settings.json
  text.py         quote-aware ; and | splitting, ANSI stripping
  builtins/
    core.py       exit help clear history alias unalias use unuse set
    files.py      cd pwd ls cat head tail grep tree cp rm vi/vim/nano
```

## What an app writes

```python
from shellkit import App, ContextKey

app = App(
    'flexflow', version=__version__,
    storage='~/.flexflow',                    # or '.refman' to keep it per project
    contexts=[
        ContextKey('case', parse=resolve_case, path=True, label='c', style='#00aaff bold'),
        ContextKey('node', parse=int, label='n'),
        ContextKey('time', parse=float, clears=('t1', 't2')),
    ],
    builtins=('core', 'files'),
    session_timeout=15,                       # None: no timeout, no `set timeout`
)
app.register(CaseCommand, DataCommand, FieldCommand)
sys.exit(app.run())          # no args -> shell; args -> run once and exit
```

## Decisions

1. **argparse** for all commands (chosen over click). `BaseCommand.setup_parser`
   is unchanged from flexflow.
2. **Commands get `ctx`.** `execute(self, args, ctx)`; ctx is the Runtime
   (`ctx.get('case')`, `ctx.console`, `ctx.out()`, `ctx.cwd`, `ctx.settings`).
   Old `execute(self, args)` still works (detected by signature), so an app
   can migrate one command at a time. `current_runtime()` covers deep helpers
   that have no ctx yet, in place of `InteractiveShell._instance`.
3. **Context arguments are declared.** `add_context_arg(parser, 'case')` adds
   a positional with `nargs='?'` whose default is a sentinel; after parsing,
   `fill_context` swaps sentinels for context values (or errors if required
   and unset). This replaces flexflow's `_inject_*_context` position tables.
   For values derived from several contexts, `resolve=(store, namespace)`
   computes the value (flexflow: a single `time` as a `--t1/--t2` window);
   `explicit(ns, dest)` tells it what the user typed. `default=` is the value
   when the context gives nothing, `type=` is applied to context values too,
   and append arguments get `[value]`.
4. **Completion is generated** by walking argparse: subcommands (with help),
   flags (with help, not repeated once used), `choices`, context keys, and
   per-argument `action.completer`. `paths(exts=...)` is provided.
5. **Context is generic.** `ContextKey(name, parse, complete, path, label,
   style, format, clears)` replaces the per-key `use_x`/`unuse_x` methods.
   `use list`, `use last` and the on-exit snapshot come from the keys.
6. **App state and launch options.** `App(setup=fn)` runs once per runtime
   and its result is `rt.state` (a database, managers). `app.launch_option()`
   adds options before the command, parsed into `rt.options`.
   `CommandError(message, status=2)` refuses input without a traceback.
7. **Apps add builtins** with `@app.builtin('web', help=...)`, so things like
   flexflow's `web`, `quota`, `du`, `find` stay in flexflow.
8. **Storage** is per app: `~/.name` by default, or a relative path to keep it
   with the project. File names match flexflow's (`history`, `aliases`,
   `settings.json`; `timeout` is stored as `timeout_minutes`), so existing
   files carry over.
9. **Python >= 3.10.**

## Line pipeline

```
input -> alias expansion (chained aliases; self-reference stops)
      -> split on unquoted ';'
      -> each part: split on unquoted '|'
           first segment: builtin / command (output captured) or OS
           later segments: OS shell, previous output on stdin
      -> '!cmd' runs cmd in the OS shell directly
```

Capture swaps the rich console's file and redirects stdout, so commands that
use plain `print()` pipe too; rich writes no ANSI to a non-terminal, and any
ANSI a command writes itself is stripped. Errors go to stderr and are not piped.

Errors: argparse errors show the failing subparser's usage and return 2;
exceptions return 1 (traceback with `set debug on` or `--debug`); SystemExit
returns its code; the shell keeps running in every case.

## Session timeout

Kept from flexflow (SIGALRM + deadline, ttl shown in the prompt), with one
change: it only interrupts the shell while it waits at the prompt. A command
that is running when the time is up finishes first, then the shell exits.

## What stays where

| shellkit | the app |
|---|---|
| registry, BaseCommand, parser build | `commands/`, `core/`, `web/`, `plt/` ... |
| shell loop, history, aliases, settings, timeout | ContextKeys and their parse/complete functions |
| pipes, chaining, file builtins | banner, examples, domain help text |
| generated completion | app builtins (`web`, `quota`, `du`, `find`) |

## Migration plan

1. **Build shellkit** from flexflow's `cli/`, with tests. *(done)*
2. **Port flexflow_manager.** *(done, merged)* Parsers take
   contexts through `add_context_arg` helpers in `src/cli/context.py`;
   `interactive.py`, `registry.py`, `parser.py` are gone. Commands still use
   `execute(self, args)`, which shellkit accepts; moving them to `ctx` can
   happen one at a time. `use case:*` needed nothing: `*` is passed through
   and the commands already handle it. The bash/zsh completion installer
   (`src/cli/completion.py`) stays in flexflow, untouched.
3. **Port reference_manager** from click to argparse. *(done, branch
   `shellkit-port`)* Each `cli/groups/*.py` group is a BaseCommand whose
   subcommands are the unchanged command functions; `repl.py`, `session.py`
   and `root.py` are gone; `use study:` is a ContextKey; `storage='.refman'`.
   It needed three shellkit additions: `App.launch_option()` (its `--db`),
   `App(setup=...)` / `rt.state` (the CliContext of managers every command
   uses), and `CommandError` (click.UsageError's replacement).

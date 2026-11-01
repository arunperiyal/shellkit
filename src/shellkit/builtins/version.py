"""
The `version` builtin: what is running, whether there is something newer,
and comments the user leaves for later.

    version [show] [--offline]     version, commit, local changes, updates
    version comment <text>         note something (a bug, a feature to add)
    version comment                list the notes
    version comment --remove N ..  drop notes once dealt with

Updates are looked for in the app's git checkout (App(source_dir=...)): its
upstream is fetched and the commits and tags it has beyond HEAD are listed.
Nothing is changed -- pulling is left to the user. An app without a checkout
shows only its version.

Each comment is stamped with the version and commit it was written against,
the time, the working directory, the context and the last command, so it
still says what it was about when it is read months later.
"""

import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from rich.markup import escape

from shellkit.builtins import Builtin

COMMENTS = 'comments.json'
FETCH_TIMEOUT = 15          # seconds for `git fetch`
SHOWN_COMMITS = 10          # new upstream commits listed by `version show`


def builtins():
    return [Builtin('version', _version, help='Show the version and updates; leave comments',
                    usage='version [show [--offline]] | version comment [text | --remove N ...]',
                    complete=_complete, own_help=True)]


# -- git ----------------------------------------------------------------------------

def _git(source: Path, *args, timeout: float = 5) -> Optional[str]:
    """Output of a git command in `source`, or None if it fails."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    try:
        done = subprocess.run(['git', '-C', str(source), *args], capture_output=True,
                              text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def checkout(rt) -> Optional[Path]:
    """The app's git checkout, or None."""
    source = getattr(rt.app, 'source_dir', None)
    if source is None or _git(Path(source), 'rev-parse', '--git-dir') is None:
        return None
    return Path(source)


def commit(rt) -> Optional[str]:
    source = checkout(rt)
    return _git(source, 'rev-parse', '--short', 'HEAD') if source else None


# -- version show -------------------------------------------------------------------

def _version(rt, argv):
    if argv and argv[0] in ('-h', '--help', 'help'):
        _help(rt)
        return 0
    if not argv or argv[0] == 'show' or argv[0] == '--offline':
        rest = argv[1:] if argv and argv[0] == 'show' else argv
        unknown = [a for a in rest if a != '--offline']
        if unknown:
            rt.error(f"version show: unknown argument '{escape(unknown[0])}'")
            return 2
        return _show(rt, offline='--offline' in rest)
    if argv[0] in ('comment', 'comments'):
        return _comment(rt, argv[1:])
    rt.error(f"version: unknown subcommand '{escape(argv[0])}' (show, comment)")
    return 2


def _row(rt, label, value):
    rt.console.print(f"  [bold]{label:<10}[/bold] {value}")


def _show(rt, offline: bool) -> int:
    import shellkit
    app = rt.app
    rt.console.print()
    rt.console.print(f"[bold cyan]{escape(app.name)}[/bold cyan] "
                     f"{escape(app.version or '(no version)')}")
    _row(rt, 'shellkit', shellkit.__version__)
    _row(rt, 'python', f"{platform.python_version()} [dim]{escape(sys.executable)}[/dim]")

    source = checkout(rt)
    if source is None:
        _comments_line(rt)
        rt.console.print()
        return 0

    _row(rt, 'source', f"{escape(str(source))}")
    branch = _git(source, 'rev-parse', '--abbrev-ref', 'HEAD') or '?'
    head = _git(source, 'log', '-1', '--format=%h %cs %s') or '?'
    tag = _git(source, 'describe', '--tags', '--exact-match')
    _row(rt, 'branch', escape(branch) + (f"  [dim]tag {escape(tag)}[/dim]" if tag else ''))
    _row(rt, 'commit', escape(head))
    changes = _git(source, 'status', '--porcelain', '--untracked-files=no')
    if changes:
        _row(rt, 'changes', f"[yellow]{len(changes.splitlines())} file(s) modified "
                            f"locally[/yellow]")

    rt.console.print()
    _updates(rt, source, offline)
    _comments_line(rt)
    rt.console.print()
    return 0


def _upstream(source: Path) -> Optional[str]:
    """The branch's upstream, or for a branch without one (a local feature
    branch) the remote's default branch: origin/HEAD, origin/main, origin/master."""
    upstream = _git(source, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    if upstream:
        return upstream
    default = _git(source, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
    for ref in filter(None, (default, 'origin/main', 'origin/master')):
        if _git(source, 'rev-parse', '--verify', '--quiet', ref) is not None:
            return ref
    return None


def _updates(rt, source: Path, offline: bool) -> None:
    upstream = _upstream(source)
    if upstream is None:
        rt.console.print("  [dim]Updates: no upstream or remote branch to compare with.[/dim]")
        return
    if offline:
        rt.console.print(f"  [dim]Updates: not fetched (--offline); as of the last "
                         f"fetch of {escape(upstream)}:[/dim]")
    else:
        remote = upstream.split('/', 1)[0]
        with rt.console.status(f"Fetching {remote}..."):
            fetched = _git(source, 'fetch', '--quiet', '--tags', remote,
                           timeout=FETCH_TIMEOUT)
        if fetched is None:
            rt.warn(f"  Could not fetch {upstream}; showing what was last fetched.")

    behind = int(_git(source, 'rev-list', '--count', f'HEAD..{upstream}') or 0)
    ahead = int(_git(source, 'rev-list', '--count', f'{upstream}..HEAD') or 0)
    # releases after HEAD: tags whose history holds HEAD, less those on HEAD itself
    at_head = set((_git(source, 'tag', '--points-at', 'HEAD') or '').split())
    newer = [t for t in (_git(source, 'tag', '--contains', 'HEAD', '--sort=-v:refname')
                         or '').split() if t not in at_head]

    if not behind:
        rt.console.print(f"  [green]✓ Up to date[/green] with {escape(upstream)}"
                         + (f" [dim]({ahead} local commit(s) not pushed)[/dim]" if ahead else ''))
        return
    rt.console.print(f"  [bold yellow]Update available:[/bold yellow] {behind} new commit(s) "
                     f"on {escape(upstream)}"
                     + (f", newest release [cyan]{escape(newer[0])}[/cyan]" if newer else ''))
    log = _git(source, 'log', f'-{SHOWN_COMMITS}', '--format=%h %cs %s', f'HEAD..{upstream}') or ''
    for line in log.splitlines():
        rt.console.print(f"    [dim]{escape(line)}[/dim]")
    if behind > SHOWN_COMMITS:
        rt.console.print(f"    [dim]... and {behind - SHOWN_COMMITS} more[/dim]")
    if ahead:
        rt.console.print(f"  [dim]{ahead} local commit(s) not on {escape(upstream)}[/dim]")
    rt.console.print(f"  [dim]To update: git -C {escape(str(source))} pull, then "
                     f"pip install -r requirements.txt if it changed[/dim]")


# -- version comment ----------------------------------------------------------------

def load_comments(rt) -> List[dict]:
    return rt.storage.load_json(COMMENTS, [])


def _save(rt, comments) -> None:
    rt.storage.save_json(COMMENTS, comments)


def _last_command(rt) -> Optional[str]:
    """The last command run before this one, from the history file."""
    from shellkit.shell import read_history
    for entry in read_history(rt.storage.path(rt.storage.HISTORY)):
        if not entry.split()[:1] == ['version']:
            return entry.replace('\n', ' ; ')
    return None


def _comment(rt, argv) -> int:
    if not argv or argv == ['--list']:
        return _list(rt)
    if argv[0] == '--remove':
        return _remove(rt, argv[1:])
    if argv[0].startswith('--'):
        rt.error(f"version comment: unknown option '{escape(argv[0])}' (--list, --remove N)")
        return 2

    text = ' '.join(argv).strip()
    comments = load_comments(rt)
    entry = {
        'id': max((c.get('id', 0) for c in comments), default=0) + 1,
        'time': datetime.now().isoformat(timespec='seconds'),
        'text': text,
        'version': rt.app.version,
        'commit': commit(rt),
        'cwd': str(rt.cwd),
        'context': rt.context.tokens(),
        'last': _last_command(rt),
    }
    comments.append(entry)
    _save(rt, comments)
    stamp = ' '.join(filter(None, [entry['version'], entry['commit']]))
    rt.console.print(f"[green]✓[/green] Comment {entry['id']} saved"
                     + (f" [dim](against {escape(stamp)})[/dim]" if stamp else ''))
    return 0


def _list(rt) -> int:
    comments = load_comments(rt)
    if not comments:
        rt.console.print("[dim]No comments. Add one with: version comment <text>[/dim]")
        return 0
    for c in comments:
        stamp = ' '.join(filter(None, [c.get('version'), c.get('commit')]))
        rt.console.print(f"[cyan]{c.get('id'):>3}[/cyan]  {escape(c.get('text', ''))}")
        rt.console.print(f"     [dim]{escape(c.get('time', ''))}  {escape(stamp)}  "
                         f"{escape(c.get('cwd', ''))}[/dim]")
        if c.get('context'):
            rt.console.print(f"     [dim]context: {escape(' '.join(c['context']))}[/dim]")
        if c.get('last'):
            rt.console.print(f"     [dim]after:   {escape(c['last'])}[/dim]")
    rt.console.print(f"[dim]{len(comments)} comment(s) in "
                     f"{escape(str(rt.storage.path(COMMENTS)))}[/dim]")
    return 0


def _remove(rt, argv) -> int:
    if not argv or not all(a.isdigit() for a in argv):
        rt.error("usage: version comment --remove N [N ...]")
        return 2
    wanted = {int(a) for a in argv}
    comments = load_comments(rt)
    kept = [c for c in comments if c.get('id') not in wanted]
    missing = sorted(wanted - {c.get('id') for c in comments})
    if len(kept) != len(comments):
        _save(rt, kept)
        rt.console.print(f"[green]✓[/green] Removed {len(comments) - len(kept)} comment(s)")
    for n in missing:
        rt.warn(f"version comment: no comment {n}")
    return 1 if missing else 0


def _comments_line(rt) -> None:
    count = len(load_comments(rt))
    if count:
        rt.console.print(f"  [dim]{count} comment(s); list them with: version comment[/dim]")


# -- help / completion --------------------------------------------------------------

def _help(rt):
    p = rt.console.print
    p()
    p("[bold cyan]version[/bold cyan]  The running version, updates, and your comments")
    p()
    p("[bold]USAGE:[/bold]")
    p("  version \\[show] \\[--offline]    [dim]# version, commit, and whether updates are available[/dim]")
    p("  version comment <text>        [dim]# note a bug or a feature wanted[/dim]")
    p("  version comment               [dim]# list the notes[/dim]")
    p("  version comment --remove N    [dim]# drop note N once dealt with[/dim]")
    p()
    p("[dim]show fetches the upstream of the app's git checkout and lists the commits "
      "and tags it has that this copy does not; --offline uses the last fetch. "
      "Nothing is installed. A comment is saved with the version, commit, time, "
      "directory, context and last command.[/dim]")
    p()


def _complete(rt, args, current):
    if not args:
        return [('show', 'Version, commit and available updates'),
                ('comment', 'Add, list or remove comments')]
    if args[0] == 'show' and len(args) == 1:
        return [('--offline', 'Do not fetch; use the last fetch')]
    if args[0] == 'comment' and len(args) == 1:
        return [('--remove', 'Remove comments by number')]
    if args[0] == 'comment' and args[1:2] == ['--remove']:
        return [(str(c['id']), c.get('text', '')) for c in load_comments(rt)]
    return []

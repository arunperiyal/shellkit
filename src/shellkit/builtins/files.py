"""
File builtins: cd, pwd, ls, cat, head, tail, grep, tree, cp, rm, vi/vim/nano.

They work on the shell's cwd and write through the runtime, so their output
can be piped (`ls | grep plt`, `cat log | tail -5`). Paths may be globs.
"""

import datetime
import glob
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

from rich import box
from rich.columns import Columns
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from shellkit.builtins import Builtin

# cat stops after this many lines of a file bigger than LARGE_FILE_BYTES
LARGE_FILE_BYTES = 1024 * 1024
LARGE_FILE_LINES = 1000


def builtins():
    files = 'Files'
    return [
        Builtin('cd', _cd, help='Change directory', usage='cd [path|-|~]',
                complete=_dirs, category=files),
        Builtin('pwd', _pwd, help='Show the working directory', category=files),
        Builtin('ls', _ls, help='List files', usage='ls [-l] [-a] [-t] [-v] [path|glob ...]',
                details="  [cyan]-l[/cyan]  Long format (size, date, name)\n"
                        "  [cyan]-a[/cyan]  Show hidden files\n"
                        "  [cyan]-t[/cyan]  Newest first\n"
                        "  [cyan]-v[/cyan]  Natural sort (RUN_2 before RUN_10)",
                complete='path', category=files),
        Builtin('cat', _cat, help='Show file contents', usage='cat <file> [files...]',
                complete='path', category=files),
        Builtin('head', _head, help='First lines of a file', usage='head [-n N] <file>',
                complete='path', category=files),
        Builtin('tail', _tail, help='Last lines of a file', usage='tail [-n N] <file>',
                complete='path', category=files),
        Builtin('grep', _grep, help='Search file contents',
                usage='grep [-i] [-r] [-l] [-A N] <pattern> [files...]',
                details="  [cyan]-i[/cyan]    Case-insensitive\n"
                        "  [cyan]-r[/cyan]    Recurse into directories\n"
                        "  [cyan]-l[/cyan]    Only the names of files with matches\n"
                        "  [cyan]-A N[/cyan]  N lines after each match\n"
                        "[dim]In a pipe after another command, the OS grep runs "
                        "instead: `ls | grep plt`.[/dim]",
                complete='path', category=files),
        Builtin('tree', _tree, help='Directory tree', usage='tree [depth] [path]',
                complete=_dirs, category=files),
        Builtin('cp', _cp, help='Copy files', usage='cp [-r] <source> [sources...] <dest>',
                complete='path', category=files),
        Builtin('rm', _rm, help='Remove files (asks first)', usage='rm [-r] [-f] <path> [paths...]',
                details="  [cyan]-r[/cyan]  Remove directories and their contents\n"
                        "  [cyan]-f[/cyan]  Do not ask",
                complete='path', category=files),
        Builtin('vi', _editor_for('vi'), help='Edit a file (also vim, nano)',
                usage='vi|vim|nano <file>', complete='path', category=files, own_help=True),
        Builtin('vim', _editor_for('vim'), complete='path', category=files,
                own_help=True, hidden=True),
        Builtin('nano', _editor_for('nano'), complete='path', category=files,
                own_help=True, hidden=True),
    ]


# -- helpers -------------------------------------------------------------------------

def _dirs(rt, args, current):
    from shellkit.completion import path_candidates
    return path_candidates(rt, current, dirs_only=True)


def _expand(rt, patterns: List[str]) -> List[Path]:
    """Resolve paths against the cwd, expanding globs. Unmatched globs warn."""
    result = []
    for pattern in patterns:
        if any(c in pattern for c in '*?['):
            matches = sorted(glob.glob(str(rt.resolve_path(pattern))))
            if not matches:
                rt.warn(f"No matches: {pattern}")
            result.extend(Path(m) for m in matches)
        else:
            result.append(rt.resolve_path(pattern))
    return result


def _split_flags(argv: List[str], known: str):
    """
    Separate single-letter flags (combinable: -rf) from other arguments.

    Returns:
        (set of flag letters, other arguments, unknown flag or None)
    """
    flags, rest = set(), []
    for arg in argv:
        if arg.startswith('-') and len(arg) > 1 and not arg.startswith('--'):
            letters = arg[1:]
            bad = [c for c in letters if c not in known]
            if bad:
                return flags, rest, f"-{bad[0]}"
            flags.update(letters)
        else:
            rest.append(arg)
    return flags, rest, None


def _line_count(argv: List[str]):
    """Parse `-n N` (or `-N`) for head/tail. Returns (count, remaining args)."""
    count, rest = 10, []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '-n' and i + 1 < len(argv):
            count = int(argv[i + 1])
            i += 2
            continue
        if re.fullmatch(r'-\d+', arg):
            count = int(arg[1:])
        else:
            rest.append(arg)
        i += 1
    return count, rest


def _shown_path(rt, path: Path) -> str:
    """A path relative to the cwd when it is under it."""
    try:
        return str(path.relative_to(rt.cwd))
    except ValueError:
        return str(path)


def format_size(size: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def _styled(rt, path: Path) -> str:
    """A name for ls/tree: dirs cyan with '/', others per the app's file_style."""
    name = escape(path.name)
    style = rt.app.file_style(path) if rt.app.file_style else None
    if path.is_dir():
        return f"[{style or 'cyan'}]{name}/[/]"
    return f"[{style}]{name}[/]" if style else name


def _natural_key(path: Path):
    parts = re.split(r'(\d+)', path.name)
    return (not path.is_dir(), [int(p) if p.isdigit() else p.lower() for p in parts])


def _readable_file(rt, path: Path, label: str) -> bool:
    if not path.exists():
        rt.error(f"{label}: no such file: {escape(str(path))}")
        return False
    if not path.is_file():
        rt.error(f"{label}: not a file: {escape(str(path))}")
        return False
    return True


# -- cd / pwd ----------------------------------------------------------------------

def _cd(rt, argv):
    if not argv or argv[0] == '~':
        target = Path.home()
    elif argv[0] == '-':
        if rt.previous_cwd is None:
            rt.error("cd: no previous directory")
            return 1
        target = rt.previous_cwd
    else:
        target = argv[0]
    try:
        new = rt.chdir(target)
    except OSError as e:
        rt.error(f"cd: {escape(str(e))}")
        return 1
    rt.console.print(f"[green]→[/green] {escape(str(new))}")
    return 0


def _pwd(rt, argv):
    rt.out(str(rt.cwd))
    return 0


# -- ls -----------------------------------------------------------------------------

def _ls(rt, argv):
    flags, paths, bad = _split_flags(argv, 'latv')
    if bad:
        rt.error(f"ls: unknown option {bad} (ls --help)")
        return 2

    if 't' in flags:
        order = lambda items: sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)
    elif 'v' in flags:
        order = lambda items: sorted(items, key=_natural_key)
    else:
        order = lambda items: sorted(items, key=lambda p: (not p.is_dir(), p.name.lower()))

    status = 0
    loose_files = []
    targets = _expand(rt, paths or ['.'])
    dirs = []
    for target in targets:
        if not target.exists():
            rt.error(f"ls: no such file or directory: {escape(str(target))}")
            status = 1
        elif target.is_dir():
            dirs.append(target)
        else:
            loose_files.append(target)

    if loose_files:
        _ls_show(rt, order(loose_files), 'l' in flags)
    for directory in dirs:
        if len(dirs) + bool(loose_files) > 1:
            rt.console.print(f"\n[bold]{escape(str(directory))}:[/bold]")
        try:
            items = list(directory.iterdir())
        except OSError as e:
            rt.error(f"ls: {escape(str(e))}")
            status = 1
            continue
        if 'a' not in flags:
            items = [p for p in items if not p.name.startswith('.')]
        if not items:
            rt.console.print("[dim]Empty directory[/dim]")
            continue
        _ls_show(rt, order(items), 'l' in flags)
    return status


def _ls_show(rt, items: List[Path], long: bool) -> None:
    if rt.capturing:
        # one name per line, so `ls | grep x` and `ls | wc -l` work
        for item in items:
            rt.out(item.name + ('/' if item.is_dir() else ''))
        return
    if not long:
        rt.console.print(Columns([_styled(rt, p) for p in items], equal=True, expand=False))
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Size", justify="right", style="yellow")
    table.add_column("Modified", style="blue")
    table.add_column("Name")
    for item in items:
        stat = item.stat()
        size = '-' if item.is_dir() else format_size(stat.st_size)
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(size, mtime, _styled(rt, item))
    rt.console.print(table)


# -- cat / head / tail ------------------------------------------------------------------

def _cat(rt, argv):
    if not argv:
        rt.error("usage: cat <file> [files...]")
        return 2
    status = 0
    files = _expand(rt, argv)
    for path in files:
        if not _readable_file(rt, path, 'cat'):
            status = 1
            continue
        if len(files) > 1:
            rt.console.print(f"\n[bold cyan]==> {escape(path.name)} <==[/bold cyan]")
        size = path.stat().st_size
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                if size <= LARGE_FILE_BYTES:
                    rt.out(f.read(), end='')
                    continue
                rt.warn(f"Large file ({format_size(size)}): first {LARGE_FILE_LINES} lines")
                for i, line in enumerate(f):
                    if i >= LARGE_FILE_LINES:
                        break
                    rt.out(line, end='')
        except OSError as e:
            rt.error(f"cat: {escape(str(e))}")
            status = 1
    return status


def _head(rt, argv):
    return _ends(rt, argv, 'head')


def _tail(rt, argv):
    return _ends(rt, argv, 'tail')


def _ends(rt, argv, which: str) -> int:
    try:
        count, paths = _line_count(argv)
    except ValueError:
        rt.error(f"{which}: -n needs a number")
        return 2
    if not paths:
        rt.error(f"usage: {which} [-n N] <file>")
        return 2
    status = 0
    for path in _expand(rt, paths):
        if not _readable_file(rt, path, which):
            status = 1
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                if which == 'head':
                    lines = []
                    for line in f:
                        if len(lines) >= count:
                            break
                        lines.append(line)
                else:
                    lines = f.readlines()[-count:] if count else []
        except OSError as e:
            rt.error(f"{which}: {escape(str(e))}")
            status = 1
            continue
        rt.out(''.join(lines), end='')
    return status


# -- grep ---------------------------------------------------------------------------

def _grep(rt, argv):
    after = 0
    args = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ('-A', '--after-context'):
            if i + 1 >= len(argv) or not argv[i + 1].isdigit():
                rt.error("grep: -A needs a number")
                return 2
            after = int(argv[i + 1])
            i += 2
            continue
        if re.fullmatch(r'-A\d+', arg):
            after = int(arg[2:])
        elif arg in ('--ignore-case', '--recursive', '--files-only'):
            args.append({'--ignore-case': '-i', '--recursive': '-r', '--files-only': '-l'}[arg])
        else:
            args.append(arg)
        i += 1

    flags, rest, bad = _split_flags(args, 'irln')
    if bad:
        rt.error(f"grep: unknown option {bad} (grep --help)")
        return 2
    if not rest:
        rt.error("usage: grep [-i] [-r] [-l] [-A N] <pattern> [files...]")
        return 2

    pattern, targets = rest[0], rest[1:] or ['*']
    try:
        regex = re.compile(pattern, re.IGNORECASE if 'i' in flags else 0)
    except re.error as e:
        rt.error(f"grep: invalid pattern: {escape(str(e))}")
        return 2

    files: List[Path] = []
    for path in _expand(rt, targets):
        if path.is_dir():
            walker = path.rglob('*') if 'r' in flags else path.glob('*')
            files.extend(p for p in walker if p.is_file())
        elif path.is_file():
            files.append(path)
        else:
            rt.warn(f"grep: no such file: {path}")

    matches_total = files_matched = 0
    for path in files:
        try:
            with open(path, encoding='utf-8', errors='strict') as f:
                lines = f.read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable

        hits = [n for n, line in enumerate(lines, 1) if regex.search(line)]
        if not hits:
            continue
        files_matched += 1
        matches_total += len(hits)
        if 'l' in flags:
            rt.out(_shown_path(rt, path))
            continue

        shown = set(hits)
        for n in hits:
            shown.update(range(n + 1, min(n + after, len(lines)) + 1))
        if len(files) > 1:
            rt.console.print(f"\n[bold cyan]{escape(_shown_path(rt, path))}[/bold cyan]")
        previous = None
        for n in sorted(shown):
            if previous is not None and n > previous + 1 and after:
                rt.console.print("[dim]--[/dim]")
            line = lines[n - 1]
            if n in hits:
                parts, last = [], 0
                for m in regex.finditer(line):
                    parts.append(escape(line[last:m.start()]))
                    parts.append(f"[yellow]{escape(m.group())}[/yellow]")
                    last = m.end()
                parts.append(escape(line[last:]))
                rt.console.print(f"[green]{n}[/green]:{''.join(parts)}", soft_wrap=True)
            else:
                rt.console.print(f"[dim]{n}-{escape(line)}[/dim]", soft_wrap=True)
            previous = n

    if not matches_total:
        rt.console.print("[dim]No matches[/dim]")
        return 1
    if not rt.capturing and 'l' not in flags:
        rt.console.print(f"\n[dim]{matches_total} matches in {files_matched} files[/dim]")
    return 0


# -- tree ------------------------------------------------------------------------------

def _tree(rt, argv):
    depth, root = 2, rt.cwd
    for arg in argv:
        if arg.isdigit():
            depth = int(arg)
        else:
            root = rt.resolve_path(arg)
    if not root.is_dir():
        rt.error(f"tree: not a directory: {escape(str(root))}")
        return 1

    tree = Tree(f"[bold cyan]{escape(root.name or str(root))}[/bold cyan]", guide_style="dim")

    def add(branch, directory: Path, level: int):
        if level >= depth:
            return
        try:
            items = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            branch.add("[red]Permission denied[/red]")
            return
        items = [p for p in items if not p.name.startswith('.')]
        for item in items[:50]:
            child = branch.add(_styled(rt, item))
            if item.is_dir():
                add(child, item, level + 1)
        if len(items) > 50:
            branch.add(f"[dim]... {len(items) - 50} more[/dim]")

    add(tree, root, 0)
    rt.console.print(tree)
    return 0


# -- cp / rm --------------------------------------------------------------------------

def _cp(rt, argv):
    argv = ['-r' if a == '--recursive' else a for a in argv]
    flags, rest, bad = _split_flags(argv, 'r')
    if bad:
        rt.error(f"cp: unknown option {bad}")
        return 2
    if len(rest) < 2:
        rt.error("usage: cp [-r] <source> [sources...] <dest>")
        return 2

    sources = _expand(rt, rest[:-1])
    dest = rt.resolve_path(rest[-1])
    if len(sources) > 1 and not dest.is_dir():
        rt.error("cp: destination must be an existing directory when copying several sources")
        return 1

    status = 0
    for src in sources:
        target = dest / src.name if dest.is_dir() else dest
        try:
            if not src.exists():
                raise FileNotFoundError(f"not found: {src}")
            if src.is_dir():
                if 'r' not in flags:
                    raise IsADirectoryError(f"is a directory (use -r): {src}")
                shutil.copytree(src, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            rt.console.print(f"  [green]copied[/green]  {escape(str(src))}  →  {escape(str(target))}")
        except OSError as e:
            rt.error(f"cp: {escape(str(e))}")
            status = 1
    return status


def _rm(rt, argv):
    argv = [{'--recursive': '-r', '--force': '-f'}.get(a, a) for a in argv]
    flags, rest, bad = _split_flags(argv, 'rf')
    if bad:
        rt.error(f"rm: unknown option {bad}")
        return 2
    if not rest:
        rt.error("usage: rm [-r] [-f] <path> [paths...]")
        return 2

    status = 0
    for target in _expand(rt, rest):
        if not target.exists() and not target.is_symlink():
            rt.error(f"rm: not found: {escape(str(target))}")
            status = 1
            continue
        is_dir = target.is_dir() and not target.is_symlink()
        if is_dir and 'r' not in flags:
            rt.error(f"rm: is a directory (use -r): {escape(str(target))}")
            status = 1
            continue
        if 'f' not in flags:
            kind = "directory and everything in it" if is_dir else "file"
            if not rt.confirm(f"  Remove {kind} [cyan]{escape(target.name)}[/cyan]?"):
                rt.console.print("  [dim]skipped[/dim]")
                continue
        try:
            shutil.rmtree(target) if is_dir else target.unlink()
            rt.console.print(f"  [green]removed[/green]  {escape(str(target))}")
        except OSError as e:
            rt.error(f"rm: {escape(str(e))}")
            status = 1
    return status


# -- editors -----------------------------------------------------------------------------

def _editor_for(name: str):
    def run(rt, argv):
        try:
            return subprocess.run([name, *argv], cwd=rt.cwd).returncode
        except FileNotFoundError:
            rt.error(f"{name} not found")
            return 127
    return run

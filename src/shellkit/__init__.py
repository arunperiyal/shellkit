"""
shellkit -- framework for prompt-based CLI programs.

    from shellkit import App, BaseCommand, ContextKey, add_context_arg

See DESIGN.md for how the pieces fit together.
"""

from shellkit.app import App
from shellkit.builtins import Builtin
from shellkit.command import BaseCommand
from shellkit.completion import paths
from shellkit.context import ContextKey, add_context_arg, explicit
from shellkit.parser import CommandError, ShellkitParser, UsageError
from shellkit.registry import CommandRegistry
from shellkit.runtime import Runtime, current_runtime
from shellkit.settings import Setting, parse_bool

__version__ = '0.1.0'

__all__ = [
    'App', 'BaseCommand', 'Builtin', 'CommandError', 'CommandRegistry', 'ContextKey', 'Runtime',
    'Setting', 'ShellkitParser', 'UsageError', 'add_context_arg', 'current_runtime', 'explicit',
    'parse_bool', 'paths',
]

"""
Argument parser that never exits the process.

Plain argparse calls sys.exit() on a bad argument or after printing --help.
Inside an interactive shell that would end the session, so ShellkitParser
raises instead and the runtime reports the error and carries on.
"""

import argparse
import sys


class UsageError(Exception):
    """A command line argparse could not parse.

    Attributes:
        parser: The (sub)parser that rejected the arguments, so its usage
                line is the one shown rather than the top-level one
    """

    def __init__(self, message, parser):
        super().__init__(message)
        self.parser = parser


class ParserExit(Exception):
    """argparse finished early on purpose, e.g. after printing --help."""

    def __init__(self, status=0):
        super().__init__(status)
        self.status = status


class CommandError(Exception):
    """
    A command refusing its input: `raise CommandError("pass --all or a key")`.

    Reported as "Error: <message>" with no traceback, and the command's
    status is `status` (2 by default, as for a usage error).
    """

    def __init__(self, message, status=2):
        super().__init__(message)
        self.status = status


class ShellkitParser(argparse.ArgumentParser):
    """
    ArgumentParser that raises UsageError / ParserExit instead of exiting.

    Subparsers created with add_subparsers() use this class too, since argparse
    gives them the class of the parser they were added to.
    """

    def error(self, message):
        raise UsageError(message, self)

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, sys.stderr)
        raise ParserExit(status)


def subparsers_action(parser):
    """Return the parser's add_subparsers() action, or None if it has none."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None

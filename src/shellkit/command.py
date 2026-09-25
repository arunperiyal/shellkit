"""
Base command class for shellkit applications.
"""

import inspect
from abc import ABC, abstractmethod


class BaseCommand(ABC):
    """
    Base class for all commands.

    Each command inherits from this class and implements the required methods.
    `name`, `description` and `category` can be plain class attributes:

        class CheckCommand(BaseCommand):
            name = "check"
            description = "Inspect data files"
            category = "Core"
    """

    @property
    @abstractmethod
    def name(self):
        """
        Command name (e.g., 'info', 'plot', 'compare')

        Returns:
            str: The command name
        """

    @property
    @abstractmethod
    def description(self):
        """
        Short description for help message

        Returns:
            str: Brief description of what the command does
        """

    @property
    def category(self):
        """
        Command category for grouped help display

        Returns:
            str: Category name (default: 'General')
        """
        return "General"

    @abstractmethod
    def setup_parser(self, subparsers):
        """
        Configure argument parser for this command

        Parameters:
            subparsers: argparse subparsers object to add this command's parser to

        Returns:
            argparse.ArgumentParser: The configured parser for this command
        """

    @abstractmethod
    def execute(self, args, ctx):
        """
        Execute the command with parsed arguments

        Parameters:
            args: Parsed arguments (argparse.Namespace). Arguments added with
                  add_context_arg() are already filled from the context.
            ctx: The Runtime -- ctx.get('case'), ctx.console, ctx.cwd,
                 ctx.settings

        Returns:
            int or None: Exit status (None counts as 0)
        """

    def show_help(self):
        """
        Show detailed help for this command

        Override to replace the argparse-generated help shown by `help <name>`.
        """
        return NotImplemented

    def show_examples(self):
        """
        Show usage examples for this command

        Override this method to provide example usage.
        """
        return NotImplemented

    # -- framework side ----------------------------------------------------

    def has_custom_help(self):
        """True if the subclass overrides show_help()."""
        return type(self).show_help is not BaseCommand.show_help

    def run(self, args, ctx):
        """
        Call execute(), with or without ctx.

        Commands written before ctx existed define execute(self, args); they
        keep working unchanged, so an app can move over one command at a time.
        """
        try:
            params = inspect.signature(self.execute).parameters
        except (TypeError, ValueError):
            params = {}
        if len(params) >= 2:
            return self.execute(args, ctx)
        return self.execute(args)

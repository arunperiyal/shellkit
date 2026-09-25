"""
Command registry.

Each App owns one registry: commands register at startup and are looked up
by name. Unlike a module-level global, two apps (or two tests) never share it.
"""


class CommandRegistry:
    """
    Registry for managing commands

    The registry maintains a collection of available commands and provides
    methods for registration, lookup, and categorization.
    """

    def __init__(self):
        """Initialize an empty command registry"""
        self._commands = {}

    def register(self, command):
        """
        Register a command class or instance

        Parameters:
            command: A BaseCommand subclass, or an instance of one

        Returns:
            BaseCommand: The registered command object

        Raises:
            ValueError: If a command with the same name is already registered
        """
        cmd = command() if isinstance(command, type) else command

        if cmd.name in self._commands:
            raise ValueError(f"Command '{cmd.name}' is already registered")

        self._commands[cmd.name] = cmd
        return cmd

    def get(self, name):
        """
        Get a command by name

        Parameters:
            name (str): The command name

        Returns:
            BaseCommand: The command object, or None if not found
        """
        return self._commands.get(name)

    def all(self):
        """
        Get all registered commands, in registration order

        Returns:
            list: List of all command objects
        """
        return list(self._commands.values())

    def by_category(self):
        """
        Get commands grouped by category

        Returns:
            dict: Dictionary mapping category names to lists of commands
        """
        categories = {}
        for cmd in self._commands.values():
            categories.setdefault(cmd.category, []).append(cmd)
        return categories

    def has_command(self, name):
        """
        Check if a command is registered

        Parameters:
            name (str): The command name

        Returns:
            bool: True if command exists, False otherwise
        """
        return name in self._commands

    def list_names(self):
        """
        Get a list of all command names

        Returns:
            list: Sorted list of command names
        """
        return sorted(self._commands.keys())

"""CLI - Display formatting for AIPass."""

import sys

from aipass.cli.apps.modules.display import console, header, success, error, warning, section


def cli_entry():
    """Console_scripts entry point for the `aipass` command."""
    from aipass.cli.apps.cli import main

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)

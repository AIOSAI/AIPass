"""Stream-routing tests for spawn's user-facing output.

Two defects found by the DPLAN-0291 live audit, both caused by the same habit —
building one logical block out of ``warning()``/``error()`` (stderr) and
``console.print()`` (stdout):

1. Every ``--help`` screen sent its ``Usage:`` line to stderr with a warning
   glyph while the body went to stdout. ``drone @spawn update --help > f``
   dropped the usage line; ``--help | grep`` missed it. @drone, @flow and
   @ai_mail all emit nothing on stderr for --help — spawn was the outlier.

2. The sync-registry report printed the "Stale"/"Unregistered" headers on
   stderr and their member names on stdout, so on stdout the stale branch
   names appeared directly under "Healthy (N)" — the report read a stale
   branch as healthy.

Requested help is not a warning, and a report section must not be split
across two streams.
"""

import pytest

from aipass.spawn.apps.modules.delete import handle_delete
from aipass.spawn.apps.modules.grant_admin import handle_grant_admin
from aipass.spawn.apps.modules.regenerate_registry import handle_regenerate_registry
from aipass.spawn.apps.modules.repair import handle_repair
from aipass.spawn.apps.modules.sync_registry import handle_sync_registry
from aipass.spawn.apps.modules.update import handle_update

HELP_HANDLERS = [
    ("update", handle_update),
    ("delete", handle_delete),
    ("repair", handle_repair),
    ("sync-registry", handle_sync_registry),
    ("regenerate-registry", handle_regenerate_registry),
    ("grant-admin", handle_grant_admin),
]

# Moving these lines onto console.print() put them through Rich's markup parser,
# which silently eats any word-like [placeholder] that is not an escaped \[.
HELP_PLACEHOLDERS = [
    ("repair", handle_repair, "[options]"),
    ("sync-registry", handle_sync_registry, "[project-path]"),
    ("regenerate-registry", handle_regenerate_registry, "[class_name | --all]"),
]


class TestHelpGoesToStdout:
    """An explicit --help is requested output: stdout, exit 0, nothing on stderr."""

    @pytest.mark.parametrize("name,handler", HELP_HANDLERS, ids=[n for n, _ in HELP_HANDLERS])
    def test_subcommand_help_is_stdout_only(self, name, handler, capsys):
        assert handler(["--help"]) == 0

        captured = capsys.readouterr()
        assert captured.err == "", f"{name} --help wrote to stderr: {captured.err!r}"
        assert "Usage" in captured.out, f"{name} --help lost its usage line from stdout"

    @pytest.mark.parametrize("name,handler,placeholder", HELP_PLACEHOLDERS, ids=[n for n, _, _ in HELP_PLACEHOLDERS])
    def test_usage_placeholders_survive_rich(self, name, handler, placeholder, capsys):
        assert handler(["--help"]) == 0

        assert placeholder in capsys.readouterr().out, f"{name} --help lost {placeholder} to the markup parser"

    def test_entry_point_help_is_stdout_only(self, capsys):
        """The global help's OPTIONS block was the loudest case — 8 warning() calls."""
        from aipass.spawn.apps.spawn import print_help

        print_help()

        captured = capsys.readouterr()
        assert captured.err == "", f"--help wrote to stderr: {captured.err!r}"
        assert "--role" in captured.out
        assert "--trace" in captured.out


class TestReportSectionsStayWhole:
    """A report section's header and its items belong on the same stream."""

    def test_stale_names_never_land_under_healthy_on_stdout(self, capsys):
        from aipass.spawn.apps.modules.sync_registry import _print_summary

        _print_summary(
            {
                "healthy": ["alpha"],
                "stale": ["ghost"],
                "unregistered": ["stranger"],
                "fixed": False,
            }
        )

        captured = capsys.readouterr()
        assert "alpha" in captured.out
        assert "ghost" not in captured.out, "stale branch name printed under the healthy list"
        assert "stranger" not in captured.out, "unregistered branch name printed under the healthy list"
        assert "ghost" in captured.err
        assert "stranger" in captured.err

# =================== AIPass ====================
# Name: support_test_operations.py
# Description: Helpers shared by the test_operations split files
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Helpers shared by the test_operations files; product: apps/handlers/dashboard and apps/modules/dashboard.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — create_fresh_dashboard, covered by tests/test_operations.py

import sys
import types

from aipass.cli.apps.modules import display
from aipass.prax.apps.handlers.dashboard import operations, refresh, status, template_differ, template_pusher
from aipass.prax.apps.modules import dashboard as dashboard_module

# Imported once at collection; conftest doubles their logger and json service per test.
_DASHBOARD_MODULES = [dashboard_module, operations, refresh, status, template_differ, template_pusher] + [
    module
    for name, module in sorted(sys.modules.items())
    if name.startswith("aipass.prax.apps.handlers.dashboard") and isinstance(module, types.ModuleType)
]


def _load_ops():
    """The operations module, bound at the top; _dashboard_quiet doubles its edges."""
    return operations


def _load_dashboard_module() -> types.ModuleType:
    """The dashboard module imported once at the top, never reloaded."""
    return dashboard_module


class _Screen:
    """What the real console showed, read with capsys; error() and warning() lines kept apart."""

    def __init__(self, capsys):
        # Per test: every branch's session pin writes these shared consoles, and a later one resets prax's.
        # Height too: with it unset, Rich answers 80 columns on a dumb terminal whatever the width pin.
        for console in (display.CONSOLE, display.err_console):
            console.width, console.height = 1000, 25
        self._capsys = capsys
        self.out = ""
        self.printed: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def read(self) -> "_Screen":
        out, err = self._capsys.readouterr()
        self.out += out
        for line in (out + err).splitlines():
            if line.startswith("❌ "):
                self.errors.append(line[len("❌ ") :])
            elif line.startswith("⚠️  "):
                self.warnings.append(line[len("⚠️  ") :])
            else:
                self.printed.append(line)
        return self

    def _evidence(self) -> str:
        return f"errors={self.errors!r} ({len(self.errors)})\nwarnings={self.warnings!r}\nprinted={self.printed!r}"

    def assert_one_error(self, message: str) -> None:
        assert self.read().errors == [message], self._evidence()

    def assert_one_warning(self, message: str) -> None:
        assert self.read().warnings == [message], self._evidence()

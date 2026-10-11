# =================== AIPass ====================
# Name: support_test_operations.py
# Description: Helpers shared by the test_operations split files
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by the test_operations files; product: apps/handlers/dashboard and apps/modules/dashboard.py."""

# Moved verbatim out of test_operations.py at its split (2026-10-08). The
# _dashboard_quiet and screen fixtures that use them live in conftest.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — create_fresh_dashboard, covered by tests/test_operations.py

import sys
import types

from aipass.prax.apps.handlers.dashboard import operations, refresh, status, template_differ, template_pusher
from aipass.prax.apps.modules import dashboard as dashboard_module

# The dashboard module and the handler modules it was built on, as imported once
# at collection. Their logger and json service are doubled before every test.
_DASHBOARD_MODULES = [dashboard_module, operations, refresh, status, template_differ, template_pusher] + [
    module
    for name, module in sorted(sys.modules.items())
    if name.startswith("aipass.prax.apps.handlers.dashboard") and isinstance(module, types.ModuleType)
]


def _load_ops():
    """The operations module, bound at the top; _dashboard_quiet doubles its edges.

    It used to be popped and reloaded per test; it holds constants only, and
    the three tests that move _PRAX_ROOT put it back themselves (prax, leg 12).
    """
    return operations


def _load_dashboard_module() -> types.ModuleType:
    """The dashboard module imported once at the top, never reloaded (prax, leg 11).
    The autouse _dashboard_quiet fixture has doubled its logger and json service."""
    return dashboard_module


class _Screen:
    """What the real console showed, read with capsys (prax, leg 11).

    printed holds every plain line of stdout and stderr other than error() and
    warning() lines, which are kept apart without their prefix. Each read() adds
    what was written since the last one."""

    def __init__(self, capsys):
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

    def assert_one_error(self, message: str) -> None:
        assert self.read().errors == [message]

    def assert_one_warning(self, message: str) -> None:
        assert self.read().warnings == [message]

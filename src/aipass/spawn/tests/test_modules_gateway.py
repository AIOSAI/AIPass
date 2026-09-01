# =================== META ====================
# Name: test_modules_gateway.py
# Description: Tests for the apps.modules package gateway re-exports
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Tests for spawn's modules-package gateway (DPLAN-0319 wave 3).

``apps/handlers/__init__.py`` refuses cross-branch handler imports at import
time, and its own refusal message points the caller at
``aipass.spawn.apps.modules``. Until this gateway existed there was nothing to
point at for the class registry, so @seedgo's architecture check carried a
drift-pinned MIRROR of the class table (their commit 5ffc468b) — which makes
the auditor a fleet-wide single point of failure the moment spawn renames a
class.

These pins guard the contract that lets that mirror die:

    from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

The gateway is a re-export, never a reimplementation. The identity pins below
(``is`` the handler's own callable) exist so that a second copy of the logic
cannot be introduced here without a test going red — a gateway that drifts from
its handler is the same failure the mirror was, one layer closer in.
"""

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SPAWN_BRANCH = Path(__file__).resolve().parents[1]


# =============================================================================
# The import path @seedgo is told to use
# =============================================================================


class TestGatewayImportPath:
    """The exact import statement that replaces seedgo's mirror."""

    def test_both_names_import_from_the_modules_package(self):
        """The documented one-liner works verbatim."""
        from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

        assert callable(get_template_dir)
        assert callable(refuse_legacy_class)

    def test_names_are_declared_public_in_all(self):
        """__all__ names them, so the export is intentional rather than incidental."""
        from aipass.spawn.apps import modules

        assert "get_template_dir" in modules.__all__
        assert "refuse_legacy_class" in modules.__all__

    def test_gateway_import_works_from_outside_the_spawn_branch(self, tmp_path):
        """The whole point: a caller outside this branch must get through.

        Run as its own process from a file that is NOT under src/aipass/spawn/
        — the same position seedgo's auditor imports from — so the pin measures
        a real outside caller rather than an in-suite import that is already
        inside the branch.
        """
        probe = tmp_path / "probe_gateway_from_outside.py"
        probe.write_text(
            textwrap.dedent(
                """
                from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

                print(get_template_dir("specialist").name)
                print(bool(refuse_legacy_class("aipass_framework")))
                """
            ).strip(),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert result.returncode == 0, f"gateway refused an outside caller:\n{result.stderr}"
        assert result.stdout.split() == ["citizen", "True"]


# =============================================================================
# Re-export, never a reimplementation
# =============================================================================


class TestGatewayIsTheHandlerItself:
    """The gateway export and the handler function are one callable."""

    def test_get_template_dir_is_the_handler_callable(self):
        from aipass.spawn.apps.modules import get_template_dir as gateway
        from aipass.spawn.apps.handlers.class_registry import get_template_dir as handler

        assert gateway is handler

    def test_refuse_legacy_class_is_the_handler_callable(self):
        from aipass.spawn.apps.modules import refuse_legacy_class as gateway
        from aipass.spawn.apps.handlers.class_registry import refuse_legacy_class as handler

        assert gateway is handler


class TestSignaturesAreStable:
    """Signature pins — seedgo calls these positionally, by name, and bare."""

    def test_get_template_dir_signature(self):
        from aipass.spawn.apps.modules import get_template_dir

        sig = inspect.signature(get_template_dir)
        assert list(sig.parameters) == ["citizen_class"]

        param = sig.parameters["citizen_class"]
        assert param.default == "specialist", "the bare call must still resolve to the default class"
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert sig.return_annotation is Path

    def test_refuse_legacy_class_signature(self):
        from aipass.spawn.apps.modules import refuse_legacy_class

        sig = inspect.signature(refuse_legacy_class)
        assert list(sig.parameters) == ["name"]

        param = sig.parameters["name"]
        assert param.default is inspect.Parameter.empty
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert param.annotation == (str | None), "None must stay callable — seedgo passes a missing class straight in"
        assert sig.return_annotation is str


# =============================================================================
# Behaviour through the gateway
# =============================================================================


class TestGetTemplateDirThroughGateway:
    """What the auditor actually asks it."""

    @pytest.mark.parametrize("citizen_class", ["manager", "specialist"])
    def test_both_live_classes_resolve_to_the_one_template(self, citizen_class):
        from aipass.spawn.apps.modules import get_template_dir

        result = get_template_dir(citizen_class)

        assert result.name == "citizen"
        assert result == SPAWN_BRANCH / "templates" / "citizen"

    def test_bare_call_resolves_to_the_default_class(self):
        from aipass.spawn.apps.modules import get_template_dir

        assert get_template_dir().name == "citizen"

    def test_retired_name_raises_naming_its_replacement(self):
        """seedgo reads this message straight into its violation text."""
        from aipass.spawn.apps.modules import get_template_dir

        with pytest.raises(ValueError) as exc:
            get_template_dir("aipass_framework")

        message = str(exc.value)
        assert "aipass_framework" in message
        assert "specialist" in message

    def test_forbidden_class_raises_by_name(self):
        from aipass.spawn.apps.modules import get_template_dir

        with pytest.raises(ValueError) as exc:
            get_template_dir("admin")

        assert "admin" in str(exc.value)

    def test_unknown_class_raises_listing_the_registered_ones(self):
        from aipass.spawn.apps.modules import get_template_dir

        with pytest.raises(ValueError) as exc:
            get_template_dir("wizard")

        message = str(exc.value)
        assert "wizard" in message
        assert "manager" in message and "specialist" in message


class TestRefuseLegacyClassThroughGateway:
    """The retired-name lane, which seedgo reports as 'not yet migrated'."""

    @pytest.mark.parametrize(
        "retired,replacement",
        [
            ("aipass_framework", "specialist"),
            ("builder", "specialist"),
            ("project_agent", "manager"),
        ],
    )
    def test_every_retired_name_names_both_values(self, retired, replacement):
        from aipass.spawn.apps.modules import refuse_legacy_class

        message = refuse_legacy_class(retired)

        assert message
        assert retired in message
        assert replacement in message

    @pytest.mark.parametrize("live", ["manager", "specialist"])
    def test_live_classes_are_not_refused(self, live):
        from aipass.spawn.apps.modules import refuse_legacy_class

        assert refuse_legacy_class(live) == ""

    def test_forbidden_is_not_a_legacy_name(self):
        """'admin' is a permanent refusal, not a rename — different lane."""
        from aipass.spawn.apps.modules import refuse_legacy_class

        assert refuse_legacy_class("admin") == ""

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_input_is_not_refused(self, empty):
        from aipass.spawn.apps.modules import refuse_legacy_class

        assert refuse_legacy_class(empty) == ""

    def test_case_insensitive(self):
        from aipass.spawn.apps.modules import refuse_legacy_class

        assert refuse_legacy_class("AIPASS_Framework")


# =============================================================================
# The guard the gateway exists to answer
# =============================================================================


class TestHandlerGuard:
    """The guard the gateway exists to answer — pinned as it actually behaves.

    MEASURED 2026-08-28, reported to @devpulse: the guard refuses an outside
    caller when it RUNS, but at real import time it is pre-empted and never
    runs. ``apps/__init__.py:1`` is ``from . import handlers`` — so importing
    anything under ``aipass.spawn.apps`` (this gateway included) executes the
    handlers package first, with a caller frame inside spawn, which the guard
    allows. ``aipass.spawn.apps.handlers`` is then in ``sys.modules`` and every
    later import from any branch is a cache hit that never reaches the guard.

    Both halves are pinned below so the state is a measurement, not a belief.
    If the pre-emption is ever fixed, the second test goes red and names what
    changed rather than leaving a silently-stale claim behind.
    """

    def test_guard_refuses_an_outside_caller_when_it_runs(self, tmp_path):
        """Called directly with an outside caller frame, the guard says no.

        The probe lives in tmp_path, not REPO_ROOT. It used to be written beside
        the repo root and unlinked in a finally — which still counts as two
        writes into a tree the suite does not own, and @seedgo's audit-tests
        write gate named them (2026-08-30). Only the CWD needs to be REPO_ROOT,
        so that aipass resolves on the import path; the file does not.
        """
        probe = tmp_path / "probe_guard_direct.py"
        probe.write_text(
            textwrap.dedent(
                """
                from aipass.spawn.apps.handlers import _guard_branch_access

                try:
                    _guard_branch_access()
                except ImportError as exc:
                    print("BLOCKED" if "ACCESS DENIED" in str(exc) else "OTHER")
                else:
                    print("ALLOWED")
                """
            ).strip(),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "BLOCKED"

    def test_import_time_enforcement_is_currently_pre_empted(self, tmp_path):
        """KNOWN HOLE — a direct handler import from outside spawn SUCCEEDS today.

        This pins the hole rather than the wish. Reported to @devpulse
        2026-08-28; the fix is @spawn's ``apps/__init__.py`` eager
        ``from . import handlers``, which is out of scope for wave 3.
        """
        probe = tmp_path / "probe_handler_from_outside.py"
        probe.write_text(
            "from aipass.spawn.apps.handlers.class_registry import get_template_dir\n"
            'print(get_template_dir("specialist").name)\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

        assert result.returncode == 0, (
            "the import-time hole appears to be CLOSED — good news. "
            "Update this pin and the class docstring, and tell @seedgo the "
            "gateway is now the only door.\n" + result.stderr
        )
        assert result.stdout.strip() == "citizen"

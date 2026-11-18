# =================== META ====================
# Name: test_modules_gateway.py
# Description: Tests for spawn's front door (__init__.py); the apps.modules package hands out nothing
# Version: 1.5.0
# Created: 2026-08-28
# Modified: 2026-11-18
# =============================================

"""Tests for __init__.py, the package door, and for apps/modules/__init__.py holding no re-exports."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(documentation) — docstrings on get_template_dir and refuse_legacy_class
# sentry: no-test-needed(ruff) — that apps/handlers/class_registry.py parses and imports

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.spawn as front_door
from aipass.spawn import get_template_dir, refuse_legacy_class
from aipass.spawn.apps import modules
from aipass.spawn.apps.handlers import bootstrap_render, class_registry, registry
from aipass.spawn.apps.modules import core


REPO_ROOT = Path(__file__).resolve().parents[4]
SPAWN_BRANCH = Path(__file__).resolve().parents[1]


class TestModulesPackageIsNoDoor:
    """The second door is retired: apps/modules/__init__.py re-exports no handler name."""

    @pytest.mark.parametrize("name", ["__all__", "get_template_dir", "refuse_legacy_class"])
    def test_the_modules_package_hands_out_no_handler_name(self, name):
        assert not hasattr(modules, name)


class TestSignaturesAreStable:
    """Signature pins — sentry calls these positionally, by name, and bare."""

    def test_get_template_dir_signature(self):

        sig = inspect.signature(get_template_dir)
        assert list(sig.parameters) == ["citizen_class"]

        param = sig.parameters["citizen_class"]
        assert param.default == "specialist", "the bare call must still resolve to the default class"
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert sig.return_annotation is Path

    def test_refuse_legacy_class_signature(self):

        sig = inspect.signature(refuse_legacy_class)
        assert list(sig.parameters) == ["name"]

        param = sig.parameters["name"]
        assert param.default is inspect.Parameter.empty
        assert param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert param.annotation == (str | None), "None must stay callable — sentry passes a missing class straight in"
        assert sig.return_annotation is str


class TestGetTemplateDirThroughTheDoor:
    """What the auditor actually asks it."""

    @pytest.mark.parametrize("citizen_class", ["manager", "specialist"])
    def test_both_live_classes_resolve_to_the_one_template(self, citizen_class):

        result = get_template_dir(citizen_class)

        assert result.name == "citizen"
        assert result == SPAWN_BRANCH / "templates" / "citizen"

    def test_bare_call_resolves_to_the_default_class(self):

        assert get_template_dir().name == "citizen"

    def test_retired_name_raises_naming_its_replacement(self):
        """sentry reads this message straight into its violation text."""

        with pytest.raises(ValueError) as exc:
            get_template_dir("aipass_framework")

        message = str(exc.value)
        assert "aipass_framework" in message
        assert "specialist" in message

    def test_forbidden_class_raises_by_name(self):

        with pytest.raises(ValueError) as exc:
            get_template_dir("admin")

        assert "admin" in str(exc.value)

    def test_unknown_class_raises_listing_the_registered_ones(self):

        with pytest.raises(ValueError) as exc:
            get_template_dir("wizard")

        message = str(exc.value)
        assert "wizard" in message
        assert "manager" in message and "specialist" in message


class TestRefuseLegacyClassThroughTheDoor:
    """The retired-name lane, which sentry reports as 'not yet migrated'."""

    @pytest.mark.parametrize(
        "retired,replacement",
        [
            ("aipass_framework", "specialist"),
            ("builder", "specialist"),
            ("project_agent", "manager"),
        ],
    )
    def test_every_retired_name_names_both_values(self, retired, replacement):
        """The refusal ties THIS retired name to THIS replacement.

        A bare ``replacement in message`` cannot fail: every refusal names both classes.
        """

        message = refuse_legacy_class(retired)

        assert f"'{retired}' now means '{replacement}'" in message, message
        assert f"Pass '{replacement}' explicitly" in message, message

    @pytest.mark.parametrize("live", ["manager", "specialist"])
    def test_live_classes_are_not_refused(self, live):

        assert refuse_legacy_class(live) == ""

    def test_forbidden_is_not_a_legacy_name(self):
        """'admin' is a permanent refusal, not a rename — different lane."""

        assert refuse_legacy_class("admin") == ""

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_input_is_not_refused(self, empty):

        assert refuse_legacy_class(empty) == ""

    def test_case_insensitive(self):

        assert refuse_legacy_class("AIPASS_Framework")


class TestHandlerGuard:
    """The fence the package door exists to answer, pinned through the real import.

    The full shape table is tests/test_handlers_fence.py.
    """

    def test_a_direct_handler_import_from_outside_spawn_is_refused(self, tmp_path):
        """A script outside any aipass tree imports a handler and is refused, by name.

        A fresh interpreter in tmp_path, so the fence's first import in that process is this one.
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
            encoding="utf-8",
            cwd=str(tmp_path),
        )

        assert result.returncode != 0, result.stdout
        assert "ACCESS DENIED" in result.stderr, result.stderr[-600:]
        assert "Caller branch: unknown" in result.stderr, result.stderr[-600:]
        assert result.stdout == ""


FRONT_DOOR_HOMES = {
    "spawn_agent": core,
    "CITIZEN_CLASSES": class_registry,
    "FORBIDDEN_CLASSES": class_registry,
    "LEGACY_CLASSES": class_registry,
    "get_available_classes": class_registry,
    "get_template_dir": class_registry,
    "refuse_legacy_class": class_registry,
    "refuse_retired_or_forbidden": class_registry,
    "validate_class": class_registry,
    "find_registry": registry,
    "get_owner": registry,
    "is_owner": registry,
    "registry_is_writable_document": registry,
    "render_bootstrap_trinity": bootstrap_render,
}


class TestFrontDoor:
    """from aipass.spawn import <name>: each name read live from its home, nothing loaded until asked."""

    def test_the_public_list_is_exactly_the_homes_table(self):
        assert sorted(front_door.__all__) == sorted(FRONT_DOOR_HOMES)
        assert set(FRONT_DOOR_HOMES) <= set(dir(front_door))

    @pytest.mark.parametrize("name", sorted(FRONT_DOOR_HOMES))
    def test_each_name_is_the_object_its_home_defines(self, name):
        assert getattr(front_door, name) is getattr(FRONT_DOOR_HOMES[name], name)

    def test_an_unknown_name_raises_attribute_error_with_no_fallback(self):
        with pytest.raises(AttributeError, match="no attribute 'door_owner'"):
            getattr(front_door, "door_owner")

    def test_a_patch_on_the_home_reaches_the_next_read_through_the_door(self, monkeypatch):
        def sentinel(start_path=None):
            return {"email": "@patched"}

        assert front_door.get_owner is registry.get_owner
        monkeypatch.setattr(registry, "get_owner", sentinel)
        assert front_door.get_owner is sentinel

    def test_a_bare_import_loads_nothing_under_apps_and_one_name_loads_only_its_home(self):
        probe = (
            "import sys, aipass.spawn as door\n"
            "print(sorted(m for m in sys.modules if m.startswith('aipass.spawn.apps')))\n"
            "door.LEGACY_CLASSES\n"
            "print('aipass.spawn.apps.handlers.class_registry' in sys.modules,"
            " 'aipass.spawn.apps.handlers.registry' in sys.modules,"
            " 'aipass.spawn.apps.modules.core' in sys.modules)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT)
        )

        assert result.returncode == 0, result.stderr[-600:]
        assert result.stdout.splitlines() == ["[]", "True False False"]

    def test_an_outside_caller_passes_the_handlers_fence_through_the_door(self, tmp_path):
        probe = tmp_path / "probe_front_door_from_outside.py"
        probe.write_text(
            "from aipass.spawn import LEGACY_CLASSES, get_owner, get_template_dir\n"
            'print(callable(get_owner), bool(LEGACY_CLASSES), get_template_dir("specialist").name)\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(probe)], capture_output=True, text=True, encoding="utf-8", cwd=str(tmp_path)
        )

        assert result.returncode == 0, result.stderr[-600:]
        assert result.stdout.split() == ["True", "True", "citizen"]

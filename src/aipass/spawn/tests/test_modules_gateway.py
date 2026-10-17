# =================== META ====================
# Name: test_modules_gateway.py
# Description: Tests for the apps.modules package gateway re-exports
# Version: 1.1.3
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/__init__.py's gateway re-exports (DPLAN-0319 wave 3)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — docstrings on get_template_dir, refuse_legacy_class and docs_page_template
# seedgo: no-test-needed(ruff) — that apps/handlers/class_registry.py and apps/handlers/docs_page.py parse and import

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.spawn.apps import modules
from aipass.spawn.apps.handlers import docs_page
from aipass.spawn.apps.handlers.class_registry import get_template_dir as _class_registry_get_template_dir
from aipass.spawn.apps.handlers.class_registry import refuse_legacy_class as _class_registry_refuse_legacy_class
from aipass.spawn.apps.handlers.docs_page import docs_page_template as _docs_page_module_docs_page_template
from aipass.spawn.apps.modules import docs_page_template, get_template_dir, refuse_legacy_class

# @seedgo imports the class registry through this gateway instead of keeping a mirror; the
# ``is`` pins fail if a second copy of the logic appears here and drifts from the handler.


REPO_ROOT = Path(__file__).resolve().parents[4]
SPAWN_BRANCH = Path(__file__).resolve().parents[1]


class TestGatewayImportPath:
    """The exact import statement that replaces seedgo's mirror."""

    def test_both_names_import_from_the_modules_package(self):
        """The documented one-liner works verbatim."""

        assert callable(get_template_dir)
        assert callable(refuse_legacy_class)

    def test_names_are_declared_public_in_all(self):
        """__all__ names them, so the export is intentional rather than incidental."""

        assert "get_template_dir" in modules.__all__
        assert "refuse_legacy_class" in modules.__all__

    def test_gateway_import_works_from_outside_the_spawn_branch(self, tmp_path):
        """The whole point: a caller outside this branch must get through.

        A separate process from a file outside src/aipass/spawn/, where seedgo's auditor imports from.
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
            encoding="utf-8",
            cwd=str(REPO_ROOT),
        )

        assert result.returncode == 0, f"gateway refused an outside caller:\n{result.stderr}"
        assert result.stdout.split() == ["citizen", "True"]

    def test_the_docs_page_door_is_public_and_answers_an_outside_caller(self, tmp_path):
        """@seedgo's docs_page render reads the skeleton through this door."""

        assert "docs_page_template" in modules.__all__

        probe = tmp_path / "probe_docs_page_from_outside.py"
        probe.write_text(
            textwrap.dedent(
                """
                from aipass.spawn.apps.modules import docs_page_template

                print(docs_page_template().splitlines()[0])
                """
            ).strip(),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
        )

        assert result.returncode == 0, f"the docs page door refused an outside caller:\n{result.stderr}"
        assert result.stdout.strip() == "[<- Back to the README](../README.md)"


class TestGatewayIsTheHandlerItself:
    """The gateway export and the handler function are one callable."""

    def test_get_template_dir_is_the_handler_callable(self):

        assert get_template_dir is _class_registry_get_template_dir

    def test_refuse_legacy_class_is_the_handler_callable(self):

        assert refuse_legacy_class is _class_registry_refuse_legacy_class

    def test_docs_page_template_is_the_handler_callable(self):

        assert docs_page_template is _docs_page_module_docs_page_template

    def test_docs_page_template_reads_the_file_on_every_call(self, tmp_path, monkeypatch):
        """No cached copy: an edit to the skeleton reaches the next render unchanged."""

        skeleton = tmp_path / "docs_page.md"
        monkeypatch.setattr(docs_page, "DOCS_PAGE_TEMPLATE", skeleton)

        skeleton.write_text("# First\n", encoding="utf-8")
        assert docs_page_template() == "# First\n"
        skeleton.write_text("# Second\n", encoding="utf-8")
        assert docs_page_template() == "# Second\n"

    def test_docs_page_template_raises_when_the_skeleton_is_gone(self, tmp_path, monkeypatch):
        """Unreachable is said, never papered over with a fallback shape."""

        monkeypatch.setattr(docs_page, "DOCS_PAGE_TEMPLATE", tmp_path / "absent.md")

        with pytest.raises(OSError):
            docs_page_template()


class TestSignaturesAreStable:
    """Signature pins — seedgo calls these positionally, by name, and bare."""

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
        assert param.annotation == (str | None), "None must stay callable — seedgo passes a missing class straight in"
        assert sig.return_annotation is str

    def test_docs_page_template_signature(self):

        sig = inspect.signature(docs_page_template)
        assert list(sig.parameters) == [], "seedgo calls the door bare on every render"
        assert sig.return_annotation is str


class TestGetTemplateDirThroughGateway:
    """What the auditor actually asks it."""

    @pytest.mark.parametrize("citizen_class", ["manager", "specialist"])
    def test_both_live_classes_resolve_to_the_one_template(self, citizen_class):

        result = get_template_dir(citizen_class)

        assert result.name == "citizen"
        assert result == SPAWN_BRANCH / "templates" / "citizen"

    def test_bare_call_resolves_to_the_default_class(self):

        assert get_template_dir().name == "citizen"

    def test_retired_name_raises_naming_its_replacement(self):
        """seedgo reads this message straight into its violation text."""

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
    """The fence the gateway exists to answer, pinned through the real import.

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

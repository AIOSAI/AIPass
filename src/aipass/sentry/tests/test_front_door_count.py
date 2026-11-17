# =================== AIPass ====================
# Name: test_front_door_count.py
# Description: front_door_count — every cross-branch import reaching under apps/, counted, never judged
# Version: 1.0.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/aipass_standards/front_door_count.py and the front-door verb."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — iter_string_imports' call reading; tests/test_checkers_batch8.py
# sentry: no-test-needed(shared) — tracked_files: git is the edge, each test hands scan_tracked its file list
# sentry: no-test-needed(constant) — print_help, print_introspection: the verb's prose

from pathlib import Path

import pytest

from aipass.sentry.apps.handlers.aipass_standards import front_door_count as fd
from aipass.sentry.apps.modules import CommandRefused
from aipass.sentry.apps.modules import front_door

#: The branch every source below pretends to sit in.
OWN = "sentry"


def _found(source, branch=OWN):
    """(line, branch, kind, via) for every finding: a site reaching under another branch's apps/."""
    return [(r.line, r.branch, r.kind, r.via) for r in fd.scan_source(source, branch) if r.kind in fd.APPS_KINDS]


def _clean(source, branch=OWN):
    """(line, branch, kind) for every cross-branch site that is not a finding."""
    return [(r.line, r.branch, r.kind) for r in fd.scan_source(source, branch) if r.kind not in fd.APPS_KINDS]


class TestStatements:
    def test_a_cross_branch_modules_import_is_found(self):
        assert _found("from aipass.cli.apps.modules import console\n") == [(1, "cli", "modules", "statement")]

    def test_a_cross_branch_handlers_import_is_found_as_handlers(self):
        source = "from aipass.flow.apps.handlers.plan.validator import validate_plan\n"
        assert _found(source) == [(1, "flow", "handlers", "statement")]

    def test_the_short_form_is_a_clean_door_site_not_a_finding(self):
        source = "from aipass.prax import logger\n"
        assert (_found(source), _clean(source)) == ([], [(1, "prax", "door")])

    def test_from_aipass_import_a_branch_is_a_clean_door_site(self):
        assert _clean("from aipass import cli\n") == [(1, "cli", "door")]

    def test_an_own_branch_apps_import_is_never_read(self):
        assert fd.scan_source("from aipass.sentry.apps.handlers.json import json_handler\n", OWN) == []

    def test_a_relative_import_is_never_read_even_when_its_path_spells_aipass(self):
        source = "from ..apps.modules import x\nfrom .aipass.cli.apps.modules import console\n"
        assert fd.scan_source(source, OWN) == []

    def test_an_import_inside_a_function_is_found(self):
        source = "def run():\n    from aipass.memory.apps.modules.fleet import fleet\n    return fleet\n"
        assert _found(source) == [(2, "memory", "modules", "statement")]

    def test_a_type_checking_import_is_found_as_type_only(self):
        source = (
            "import typing\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from aipass.cli.apps.modules.display import console\n"
            "if typing.TYPE_CHECKING:\n"
            "    from aipass.prax.apps.modules.logger import system_logger\n"
            "else:\n"
            "    from aipass.prax.apps.modules.logger import system_logger\n"
        )
        assert _found(source) == [
            (4, "cli", "modules", "type_only"),
            (6, "prax", "modules", "type_only"),
            (8, "prax", "modules", "statement"),
        ]

    def test_import_as_is_found(self):
        assert _found("import aipass.trigger.apps.modules.core as core\n") == [(1, "trigger", "modules", "statement")]

    def test_a_path_under_apps_that_is_neither_modules_nor_handlers_is_other(self):
        assert _found("from aipass.drone.apps.drone import main\n") == [(1, "drone", "other", "statement")]

    def test_a_nested_lib_target_belongs_to_the_branch_after_aipass(self):
        source = (
            "from aipass.skills.lib.drone_commands.apps.handlers.run import go\nfrom aipass.skills.lib.x import y\n"
        )
        assert _found(source) == [(1, "skills", "handlers", "statement")]
        assert _clean(source) == [(2, "skills", "elsewhere")]


class TestStrings:
    def test_an_import_module_string_is_found_as_string(self):
        source = 'import importlib\nm = importlib.import_module("aipass.memory.apps.modules.door_entry_limits")\n'
        assert _found(source) == [(2, "memory", "modules", "string")]

    def test_a_patch_string_is_found_as_string(self):
        source = 'from unittest.mock import patch\nwith patch("aipass.cli.apps.modules.display.console"):\n    pass\n'
        assert _found(source) == [(2, "cli", "modules", "string")]

    def test_a_patch_of_the_files_own_branch_is_never_read(self):
        source = 'from unittest.mock import patch\nwith patch("aipass.sentry.apps.modules.checklist.run"):\n    pass\n'
        assert fd.scan_source(source, OWN) == []

    def test_a_string_whose_apps_is_not_a_segment_is_not_counted(self):
        source = 'import importlib\nimportlib.import_module("aipass.cli.apps_legacy.x")\n'
        assert fd.scan_source(source, OWN) == []

    def test_the_same_path_in_a_docstring_and_a_log_message_is_prose(self):
        source = (
            '"""Reach it as from aipass.cli.apps.modules import console."""\n'
            "from aipass.prax import logger\n"
            'logger.info("aipass.cli.apps.modules.display moved")\n'
            "# from aipass.flow.apps.handlers.plan import x\n"
        )
        assert _found(source) == []


class TestDoors:
    def test_a_starred_all_hands_out_the_list_it_unpacks(self):
        source = '_LAZY = ("console", "error")\n__all__ = [*_LAZY, "escape"]\ndef __getattr__(n):\n    pass\n'
        assert fd.door_names(source) == ("console", "error", "escape")

    def test_all_wins_over_the_files_other_bindings(self):
        assert fd.door_names('import importlib\n__all__ = ["logger"]\n') == ("logger",)

    def test_a_marker_file_hands_out_nothing(self):
        assert fd.door_names('"""Package marker."""\n__version__ = "1.0"\n') == ()


def _tree(root: Path, files: dict) -> list:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return sorted(files)


class TestFleet:
    FILES = {
        "src/aipass/alpha/apps/modules/a.py": (
            "from aipass.beta.apps.modules.door_x import f\n"
            "from aipass.alpha.apps.handlers.h import g\n"
            "from aipass.beta import name\n"
        ),
        "src/aipass/alpha/tests/test_a.py": "from aipass.beta.apps.handlers.h import k\n",
        "src/aipass/beta/__init__.py": '__all__ = ["name"]\n',
        "src/aipass/alpha/__init__.py": "",
        "tools/outside.py": "from aipass.alpha.apps.modules import a, b\n",
    }

    def test_each_site_lands_in_its_importer_and_target_columns_by_scope(self, tmp_path):
        result = fd.scan_tracked(tmp_path, _tree(tmp_path, self.FILES))
        rows = fd.tally(result["sites"])["rows"]
        assert (rows["alpha"]["out:prod"], rows["alpha"]["out:tests"]) == (1, 1)
        assert (rows["beta"]["in:prod"], rows["beta"]["in:tests"], rows["beta"]["in:door:prod"]) == (1, 1, 1)
        assert (rows["beta"]["in:modules"], rows["beta"]["in:handlers"]) == (1, 1)
        assert rows[fd.OUTSIDE]["out:prod"] == 1

    def test_a_package_import_names_each_module_it_reaches(self, tmp_path):
        result = fd.scan_tracked(tmp_path, _tree(tmp_path, self.FILES))
        assert fd.tally(result["sites"])["modules"]["alpha"] == {"apps.modules.a": 1, "apps.modules.b": 1}

    def test_doors_report_names_and_empty_top_files(self, tmp_path):
        result = fd.scan_tracked(tmp_path, _tree(tmp_path, self.FILES))
        assert result["doors"] == {"alpha": (), "beta": ("name",)}

    def test_an_unparseable_file_is_named_and_not_counted(self, tmp_path):
        files = _tree(tmp_path, {"src/aipass/alpha/apps/t.py": "from aipass.beta.apps.modules import {{x}}\n"})
        result = fd.scan_tracked(tmp_path, files)
        assert (result["unparseable"], result["sites"]) == (["src/aipass/alpha/apps/t.py"], [])


class TestVerb:
    def test_an_unknown_option_is_refused_by_name(self):
        with pytest.raises(CommandRefused) as refused:
            front_door.handle_command("front-door", ["scan", "--fix"])
        assert (refused.value.code, refused.value.token) == (7, "--fix")

# =================== AIPass ====================
# Name: test_checkers_batch7_imports.py
# Description: imports_check and one_logger_check rulings (split from test_checkers_batch7.py)
# Version: 1.7.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/aipass_standards/imports_check.py, one_logger_check.py and logging_allowed.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.sentry.apps.handlers.aipass_standards import (
    imports_check,
    log_handler_check,
    log_visibility_check,
    logging_allowed,
    one_logger_check,
)
from aipass.sentry.apps.handlers.aipass_standards.imports_check import (
    check_handler_independence,
    check_import_order,
    check_no_aipass_root,
    check_no_bare_imports,
    check_no_sys_path,
    check_prax_logger,
    filter_docstrings,
    find_import_section_end,
)
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE
from aipass.sentry.tests.support_checkers_batch7 import _lines

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestFilterDocstrings:
    """Tests for filter_docstrings."""

    def test_removes_multiline_docstring(self):
        """Multi-line docstring lines are removed."""
        lines = _lines('"""\nThis is a docstring.\n"""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("docstring" in ln for ln in result)

    def test_removes_single_line_docstring(self):
        """Single-line docstring is removed."""
        lines = _lines('"""Module docstring."""\nimport os\n')
        result = filter_docstrings(lines)
        assert any("import os" in ln for ln in result)
        assert not any("Module docstring" in ln for ln in result)

    def test_preserves_code(self):
        """Non-docstring lines are preserved."""
        lines = _lines("import os\nimport sys\n")
        result = filter_docstrings(lines)
        assert len([ln for ln in result if ln.strip()]) == 2


class TestFilterDocstringsBlanksProseAndStringBodiesOnly:
    """filter_docstrings blanks docstrings and string bodies; every code line survives."""

    def test_a_def_sharing_its_line_with_a_one_line_docstring_survives(self):
        out = filter_docstrings(_lines('import os\ndef f(): """Doc."""\n'))
        assert out[1] == 'def f(): """Doc."""'

    def test_a_docstring_past_the_other_delimiter_stays_blank(self):
        out = filter_docstrings(_lines('"""Doc.\n\'\'\'\nAIPASS_ROOT lives here\n"""\nimport os\n'))
        assert out[2] == "\n"

    def test_a_line_opening_a_triple_quoted_literal_is_code(self):
        out = filter_docstrings(_lines('import os\nX = os.environ["AIPASS_ROOT"] + """\nbody\n"""\n'))
        assert out[1:4] == ['X = os.environ["AIPASS_ROOT"] + """', "\n", "\n"]


class TestFindImportSectionEnd:
    """Tests for find_import_section_end."""

    def test_finds_def(self):
        """Stops at first def statement."""
        lines = _lines("import os\nimport sys\n\ndef main():\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 3  # index of 'def main():'

    def test_finds_class(self):
        """Stops at first class statement."""
        lines = _lines("import os\n\nclass Foo:\n    pass\n")
        result = find_import_section_end(lines)
        assert result == 2  # index of 'class Foo:'

    def test_no_def_returns_length(self):
        """File with no def/class returns length of lines."""
        lines = _lines("import os\nimport sys\nx = 42\n")
        result = find_import_section_end(lines)
        assert result == len(lines)


class TestCheckNoAipassRoot:
    """Tests for check_no_aipass_root."""

    def test_clean_file_passes(self, tmp_path):
        """File without AIPASS_ROOT passes."""
        lines = _lines("import os\nfrom aipass.prax import logger\n")
        result = check_no_aipass_root(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is True

    def test_aipass_root_usage_fails(self, tmp_path):
        """File using AIPASS_ROOT fails."""
        lines = _lines("root = AIPASS_ROOT / 'config'\n")
        result = check_no_aipass_root(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False
        assert "AIPASS_ROOT" in result["message"]


class TestCheckNoSysPath:
    """Tests for check_no_sys_path."""

    def test_clean_file_passes(self, tmp_path):
        """File without sys.path hacking passes."""
        lines = _lines("import os\nimport sys\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is True

    def test_sys_path_insert_fails(self, tmp_path):
        """File with sys.path.insert fails."""
        lines = _lines("import sys\nsys.path.insert(0, '/my/path')\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False
        assert "sys.path" in result["message"]

    def test_sys_path_append_fails(self, tmp_path):
        """File with sys.path.append fails."""
        lines = _lines("import sys\nsys.path.append('/my/path')\n")
        result = check_no_sys_path(lines, (tmp_path / "test.py").as_posix())
        assert result["passed"] is False


class TestCheckPraxLogger:
    """check_prax_logger convicts stdlib logging, never the absence of a prax import."""

    def _check(self, source: str, tmp_path) -> dict:
        result = check_prax_logger(_lines(source), (tmp_path / "test.py").as_posix())
        assert result is not None
        return result

    def test_a_file_that_never_logs_passes_without_a_prax_import(self, tmp_path):
        assert self._check("import os\nimport sys\n\nprint(os.sep, sys.argv)\n", tmp_path)["passed"] is True

    def test_a_stdlib_level_call_fails_and_names_its_line(self, tmp_path):
        result = self._check("import logging\n\n\ndef f():\n    logging.info('x')\n", tmp_path)
        assert result["passed"] is False
        assert "lines [5]" in result["message"]

    def test_a_stdlib_get_logger_fails(self, tmp_path):
        assert self._check("import logging\nLOG = logging.getLogger(__name__)\n", tmp_path)["passed"] is False

    def test_a_level_call_on_a_bound_stdlib_logger_fails(self, tmp_path):
        source = "from logging import getLogger\nlog = getLogger(__name__)\n\n\ndef f():\n    log.warning('x')\n"
        result = self._check(source, tmp_path)
        assert result["passed"] is False
        assert "lines [2, 6]" in result["message"]

    def test_a_self_attribute_bound_to_a_stdlib_logger_fails(self, tmp_path):
        source = (
            "import logging as lg\n\n\nclass C:\n    def __init__(self):\n"
            "        self.log = lg.getLogger('c')\n\n    def run(self):\n        self.log.error('x')\n"
        )
        assert "lines [6, 9]" in self._check(source, tmp_path)["message"]

    def test_the_failure_message_offers_both_spellings(self, tmp_path):
        message = self._check("import logging\nlogging.error('x')\n", tmp_path)["message"]
        assert "from aipass.prax import logger" in message
        assert "from aipass import prax" in message

    def test_a_level_call_on_a_non_logging_name_is_not_convicted(self, tmp_path):
        source = "import argparse\nimport logging\n\nparser = argparse.ArgumentParser()\nparser.error('x')\n"
        assert self._check(source, tmp_path)["passed"] is True

    def test_logging_named_only_inside_a_string_is_not_convicted(self, tmp_path):
        assert self._check("SAMPLE = 'import logging; logging.info(1)'\n", tmp_path)["passed"] is True

    def test_an_unparseable_file_fails_rather_than_reading_as_passed(self, tmp_path):
        result = self._check("def broken(:\n", tmp_path)
        assert result["passed"] is False
        assert result["message"].startswith("Unparseable source")

    def test_logging_constants_alone_are_not_convicted(self, tmp_path):
        assert self._check("import logging\nLEVEL = logging.WARNING\n", tmp_path)["passed"] is True


class TestCheckPraxLoggerAcceptsBothBindings:
    """The standard is about ROUTING; both bindings route identically."""

    def _check(self, source: str, tmp_path) -> dict:
        result = check_prax_logger(_lines(source), (tmp_path / "test.py").as_posix())
        assert result is not None
        return result

    def test_the_rebindable_module_form_passes(self, tmp_path):
        assert self._check("from aipass import prax\nprax.logger.info('x')\n", tmp_path)["passed"] is True

    def test_the_object_form_passes(self, tmp_path):
        assert self._check("from aipass.prax import logger\nlogger.info('x')\n", tmp_path)["passed"] is True

    def test_a_prax_logger_beside_an_unused_stdlib_import_passes(self, tmp_path):
        source = "import logging\nfrom aipass.prax import logger\n\nlogger.setLevel(logging.INFO)\nlogger.info('x')\n"
        assert self._check(source, tmp_path)["passed"] is True


class TestImportsHandlerIndependence:
    """Tests for imports_check.check_handler_independence."""

    def test_clean_handler_passes(self, tmp_path):
        """Handler without parent module imports passes."""
        lines = _lines("from aipass.prax import logger\n")
        result = check_handler_independence(
            lines, (tmp_path / "sentry" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is True

    def test_parent_module_import_fails(self, tmp_path):
        """Handler importing from parent branch modules fails."""
        lines = _lines("from sentry.apps.modules.audit import run\n")
        result = check_handler_independence(
            lines, (tmp_path / "sentry" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is False
        assert "parent module" in result["message"]

    def test_infrastructure_import_passes(self, tmp_path):
        """prax and cli through their front doors are allowed."""
        lines = _lines("from aipass.prax import logger\nfrom aipass.cli import header\n")
        result = check_handler_independence(
            lines, (tmp_path / "sentry" / "apps" / "handlers" / "json" / "handler.py").as_posix()
        )
        assert result is not None
        assert result["passed"] is True


class TestCheckImportOrder:
    """Tests for check_import_order."""

    def test_correct_order_passes(self, tmp_path):
        """Stdlib before aipass imports passes."""
        lines = _lines("import os\nimport sys\nfrom aipass.prax import logger\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_wrong_order_fails(self, tmp_path):
        """Aipass import before stdlib fails."""
        lines = _lines("from aipass.prax import logger\nimport os\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "before stdlib" in result["message"]

    def test_no_imports_returns_none(self, tmp_path):
        """File with no imports returns None."""
        lines = _lines("x = 42\n")
        result = check_import_order(lines, (tmp_path / "test.py").as_posix())
        assert result is None


class TestCheckNoBareImports:
    """Tests for check_no_bare_imports."""

    def test_proper_namespace_passes(self, tmp_path):
        """Import using aipass.* namespace passes."""
        lines = _lines("from aipass.sentry.apps.handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_bare_handler_import_fails(self, tmp_path):
        """Bare 'from handlers.X' import fails."""
        lines = _lines("from handlers.json import json_handler\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "bare import" in result["message"]

    def test_bare_module_import_fails(self, tmp_path):
        """Bare 'from drone.apps...' without aipass prefix fails."""
        lines = _lines("from drone.apps.modules.commander import route\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "missing aipass." in result["message"]

    @pytest.mark.parametrize(
        "source, path, cure",
        [
            (
                "from handlers.json import j\n",
                "src/aipass/sentry/apps/modules/m.py",
                "(must use aipass.* namespace: from aipass.sentry.apps.handlers.json)",
            ),
            (
                "from handlers.json import j\n",
                "m.py",
                "(must use aipass.* namespace: from aipass.<branch>.apps.handlers.json)",
            ),
            (
                "from sentry.apps.modules.audit import run\n",
                "src/aipass/sentry/apps/modules/m.py",
                "(missing aipass. prefix; should be from aipass.sentry.apps.modules.audit)",
            ),
            (
                "from drone.apps.modules.commander import route\n",
                "src/aipass/sentry/apps/modules/m.py",
                "(missing aipass. prefix; another branch: its front door, from aipass.drone import <name>)",
            ),
        ],
    )
    def test_the_bare_import_cure_is_the_own_branch_path_or_the_front_door(self, source, path, cure):
        """FPLAN-1024: inside its branch a file imports any path; another branch through its door."""
        result = check_no_bare_imports(_lines(source), path)
        assert result is not None
        assert result["message"].endswith(cure)

    def test_stdlib_import_passes(self, tmp_path):
        """Standard library imports pass."""
        lines = _lines("import os\nfrom pathlib import Path\n")
        result = check_no_bare_imports(lines, (tmp_path / "test.py").as_posix())
        assert result is not None
        assert result["passed"] is True


class TestAipassRootIsMatchedAsATokenNotASubstring:
    """`AIPASS_ROOTS.json` is a FILENAME, not the AIPASS_ROOT env var."""

    def _check(self, line):
        return check_no_aipass_root([line + "\n"], "mod.py", [])

    def test_the_env_var_is_still_caught(self):
        assert not self._check('root = os.environ["AIPASS_ROOT"]')["passed"]

    def test_the_env_var_via_getenv_is_still_caught(self):
        assert not self._check('root = os.getenv("AIPASS_ROOT")')["passed"]

    def test_a_bare_reference_is_still_caught(self):
        assert not self._check("path = AIPASS_ROOT / 'x'")["passed"]

    def test_the_declared_roots_filename_is_not_a_violation(self):
        """@memory's exact line."""
        assert self._check('DECLARED_ROOTS = "AIPASS_ROOTS.json"')["passed"]

    def test_a_future_aipass_root_map_is_not_a_violation_either(self):
        """The report named this one specifically as the next collision."""
        assert self._check('NAME = "AIPASS_ROOT_MAP.json"')["passed"]

    def test_aipass_roots_registry_is_not_a_violation(self):
        assert self._check('NAME = "AIPASS_ROOTS_REGISTRY.json"')["passed"]

    def test_a_longer_name_ending_in_the_token_is_not_a_violation(self):
        """Prefix-only matching would still convict this one."""
        assert self._check('NAME = "MY_AIPASS_ROOT"')["passed"]

    def test_the_env_var_inside_an_fstring_is_still_caught(self):
        assert not self._check('msg = f"{AIPASS_ROOT}/x"')["passed"]


class TestImportsCheckLineNumbersSurviveDocstringFiltering:
    """A reported line number must name the line in the FILE."""

    def test_filter_docstrings_preserves_the_line_count(self):
        source = ['"""doc\n', "more doc\n", '"""\n', "import os\n"]
        assert len(filter_docstrings(source)) == len(source)

    def test_the_docstring_body_is_still_neutralised(self):
        """Preserving the line must not un-filter its content."""
        out = filter_docstrings(['"""\n', "AIPASS_ROOT lives here\n", '"""\n', "import os\n"])
        assert "AIPASS_ROOT" not in "".join(out)

    def test_a_violation_after_a_docstring_reports_its_real_line(self):
        source = ['"""\n', "a\n", "b\n", "c\n", '"""\n', 'x = os.environ["AIPASS_ROOT"]\n']
        result = check_no_aipass_root(filter_docstrings(source), "mod.py", [])
        assert not result["passed"]
        assert "line 6" in result["message"], result["message"]

    def test_the_real_reported_file_now_passes_end_to_end(self):
        """@memory's actual file, through the real entry point."""
        from pathlib import Path

        target = Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "monitor" / "registry_scope.py"
        if not target.exists():
            import pytest

            pytest.skip("registry_scope.py not on disk")
        rows = imports_check.check_module(str(target))["checks"]
        root_rows = [r for r in rows if r["name"] == "No AIPASS_ROOT"]
        assert root_rows and root_rows[0]["passed"], root_rows


_K2_CONSTANT = (
    'import os\nLOG = os.path.join("logs", "bridge.log")\n\n\n'
    'def rec(line):\n    with open(LOG, "a", encoding="utf-8") as h:\n        h.write(line)\n'
)
_K3_STAMPED = (
    "from datetime import datetime\n\n\ndef _log(message):\n"
    '    stamp = datetime.now().strftime("%H:%M:%S")\n    console.print(f"[{stamp}] {message}")\n'
)


_PUBLISHED_ALLOWED = 'LOGGING_ALLOWED = (("prax/apps/handlers/logging/setup.py", "builds door one"),)\n'
_PUBLISHED_DOORS = 'LOGGER_DOORS = (("prax/apps/handlers/logging/trail.py", "door two"),)\n'
_LEVEL_CLASS = "class Door:\n    def info(self, m):\n        pass\n\n    def error(self, m):\n        pass\n"


@pytest.fixture
def published(tmp_path, monkeypatch):
    """Prax's published lists, as prax writes them: setup.py for stdlib, trail.py for a door class."""
    source = tmp_path / "published_logger.py"
    source.write_text(_PUBLISHED_ALLOWED + _PUBLISHED_DOORS, encoding="utf-8")
    monkeypatch.setattr(logging_allowed, "PRAX_LOGGER", source)
    return source


def _judge(tmp_path, source, rel="flow/apps/handlers/mod.py"):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return one_logger_check.check_module(str(target))


def _keys(answer):
    return sorted(c["key"] for c in answer["checks"] if not c["passed"])


class TestOneLoggerConvictsEveryLoggerButPrax:
    @pytest.mark.parametrize(
        ("source", "key"),
        [
            ("import logging\nlog = logging.getLogger(__name__)\n", "K0"),
            ("from logging.handlers import RotatingFileHandler\n", "K0"),
            (
                "def append_trail(p, e):\n    pass\n\n\n"
                "class Trail:\n    def _emit(self, m):\n        append_trail(1, m)\n\n"
                "    def info(self, m):\n        self._emit(m)\n\n    def error(self, m):\n        self._emit(m)\n",
                "K1",
            ),
            (_K2_CONSTANT, "K2"),
            (
                'from pathlib import Path\nNAME = "serve.log"\n\n\n'
                'def log_path():\n    return Path("logs") / NAME\n\n\n'
                'def start():\n    with open(log_path(), "a", encoding="utf-8") as s:\n        s.write("x")\n',
                "K2",
            ),
            (_K3_STAMPED, "K3"),
            ('import sys\n\n\ndef _stderr(msg):\n    sys.stderr.write(msg + "\\n")\n    sys.stderr.flush()\n', "K3"),
            (
                "import sys\n\n\ndef _log(level, message):\n    try:\n        from aipass.prax import logger\n\n"
                "        getattr(logger, level)(message)\n    except Exception:\n"
                '        sys.stderr.write(f"{message} (prax unavailable)\\n")\n',
                "K3",
            ),
        ],
        ids=[
            "stdlib",
            "stdlib_handlers",
            "delegating_class",
            "log_constant",
            "log_function",
            "stamped_print",
            "stderr_helper",
            "prax_then_stderr",
        ],
    )
    def test_each_key_convicts_its_logger_and_names_the_prax_door(self, tmp_path, source, key):
        answer = _judge(tmp_path, source)
        assert (answer["score"], _keys(answer)) == (0, [key])
        assert "from aipass.prax import logger" in next(c["message"] for c in answer["checks"] if not c["passed"])

    @pytest.mark.parametrize(
        "source",
        [
            '"""Never import logging here."""\n# import logging\nx = "import logging"\n',
            "class Status:\n    def ok(self, d):\n        pass\n\n    def info(self, d):\n        pass\n\n"
            "    def warn(self, d):\n        pass\n",
            'LOG = "watch.log"\n\n\ndef read():\n    with open(LOG, encoding="utf-8") as h:\n        return h.read()\n',
            'def rec(line):\n    with open("trail.jsonl", "a", encoding="utf-8") as h:\n        h.write(line)\n',
            'import sys\n\n\ndef _write(line):\n    sys.stdout.write(line + "\\n")\n',
            'def _title(text):\n    console.print(f"[bold]{text}[/bold]")\n',
            "import sys\n\n\ndef _ask(prompt):\n    sys.stderr.write(prompt)\n    return input()\n",
            "from aipass.prax import logger\n\n\ndef run():\n    logger.info('ran')\n",
        ],
        ids=[
            "mentions_only",
            "one_level_method",
            "log_reader",
            "jsonl_record",
            "stdout_protocol",
            "unstamped_ui",
            "stderr_prompt_returns",
            "prax_door",
        ],
    )
    def test_a_file_with_no_logger_but_prax_passes(self, tmp_path, source):
        answer = _judge(tmp_path, source)
        assert (answer["passed"], answer["score"], _keys(answer)) == (True, 100, [])

    def test_a_bypass_row_waives_nothing(self, tmp_path):
        target = tmp_path / "flow/apps/handlers/mod.py"
        target.parent.mkdir(parents=True)
        target.write_text("import logging\n", encoding="utf-8")
        rules = [{"file": "apps/handlers/mod.py", "standard": "one_logger", "reason": "waive it"}]
        assert one_logger_check.check_module(str(target), bypass_rules=rules)["score"] == 0

    @pytest.mark.parametrize(
        ("rel", "source", "passed"),
        [
            ("hooks/apps/handlers/bridges/claude.py", _K2_CONSTANT, True),
            ("hooks/apps/handlers/bridges/claude_copy.py", _K2_CONSTANT, False),
            ("prax/apps/handlers/logging/setup.py", "import logging\n", True),
            ("prax/apps/handlers/logging/jsonl_writer.py", "import logging\n", False),
            ("prax/apps/handlers/logging/setup.py", _K3_STAMPED, False),
            ("prax/apps/handlers/logging/trail.py", _LEVEL_CLASS, True),
            ("prax/apps/modules/logger.py", _LEVEL_CLASS, False),
        ],
        ids=[
            "floor_named",
            "floor_namesake",
            "prax_published",
            "prax_unpublished",
            "published_for_another_key",
            "door_published",
            "door_unpublished",
        ],
    )
    def test_only_a_named_file_passes_and_only_for_its_key(self, tmp_path, published, rel, source, passed):
        answer = _judge(tmp_path, source, rel)
        assert answer["passed"] is passed
        assert any("allowed: " in c["message"] for c in answer["checks"]) is passed

    @pytest.mark.parametrize(
        ("published_source", "missing"),
        [
            (None, "LOGGING_ALLOWED"),
            (_PUBLISHED_DOORS, "LOGGING_ALLOWED"),
            (_PUBLISHED_ALLOWED, "LOGGER_DOORS"),
        ],
        ids=["file_gone", "allowed_gone", "doors_gone"],
    )
    def test_an_unreadable_published_list_refuses_every_file(self, tmp_path, monkeypatch, published_source, missing):
        source = tmp_path / "published_logger.py"
        if published_source is not None:
            source.write_text(published_source, encoding="utf-8")
        monkeypatch.setattr(logging_allowed, "PRAX_LOGGER", source)
        answer = _judge(tmp_path, "x = 1\n")
        assert answer["score"] == 0
        assert missing in answer["checks"][0]["message"]

    def test_it_is_advisory_and_production_only(self):
        assert (one_logger_check.ADVISORY, one_logger_check.CHECKLIST_ADVISES, one_logger_check.APPLIES_TO) == (
            True,
            True,
            "production",
        )


class TestTheOldLoggingExemptionsReadPraxsList:
    @pytest.mark.parametrize("branch", ["prax", "flow"], ids=["prax_logger_module", "namesake"])
    def test_imports_exempts_no_logger_module_from_the_stdlib_conviction(self, tmp_path, branch):
        target = tmp_path / branch / "apps" / "modules" / "logger.py"
        target.parent.mkdir(parents=True)
        body = "".join(f"x{i} = {i}\n" for i in range(25))
        target.write_text("import logging\n\nlog = logging.getLogger(__name__)\n" + body, encoding="utf-8")
        checks = imports_check.check_module(str(target))["checks"]
        assert not all(c["passed"] for c in checks if c["name"].startswith("Prax logger"))

    @pytest.mark.parametrize(
        ("rel", "passed"),
        [("prax/apps/handlers/logging/setup.py", True), ("prax/apps/handlers/logging/direct.py", False)],
        ids=["published", "unpublished"],
    )
    def test_log_visibility_passes_only_the_files_prax_publishes(self, tmp_path, published, rel, passed):
        target = tmp_path / rel
        target.parent.mkdir(parents=True)
        target.write_text("import logging\n\nlog = logging.getLogger(__name__)\n", encoding="utf-8")
        assert log_visibility_check.check_module(str(target))["passed"] is passed

    def test_log_handler_exempts_no_prax_file(self, tmp_path):
        target = tmp_path / "prax/apps/handlers/logging/setup.py"
        target.parent.mkdir(parents=True)
        target.write_text('import logging\n\nh = logging.FileHandler("x.log")\n', encoding="utf-8")
        assert log_handler_check.check_module(str(target))["passed"] is False


_FILLER = "".join(f"x{i} = {i}\n" for i in range(20))  # past the small-file exemption, so prax's rule is asked


def _imports_under(tmp_path, source, rel="mybr/apps/modules/mod.py", **scope) -> dict:
    """imports_check on ``rel`` under one row of this scope (no row when no scope is given)."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    rules = [{"file": rel.split("/", 1)[1], "standard": "imports", "reason": "t", **scope}] if scope else []
    return imports_check.check_module(str(target), bypass_rules=rules)


def _named(result, prefix) -> dict:
    return next(c for c in result["checks"] if c["name"].startswith(prefix))


class TestImportsAsksTheBypassTablePerSite:
    """Each offending line is a site (FILE_SCOPE in the import section); import order is file-level."""

    @pytest.mark.parametrize(
        ("source", "check"),
        [
            ('"""Doc."""\nimport os\nA = os.environ["AIPASS_ROOT"]\nB = os.getenv("AIPASS_ROOT")\n', "No AIPASS_ROOT"),
            ('"""Doc."""\nimport sys\nsys.path.insert(0, "a")\nsys.path.append("b")\n', "No sys.path hacking"),
        ],
        ids=["aipass_root", "sys_path"],
    )
    def test_a_line_row_waives_its_line_and_the_next_line_still_convicts(self, tmp_path, source, check):
        open_row = _named(_imports_under(tmp_path, source), check)
        one = _imports_under(tmp_path, source, lines=[3])
        assert (open_row["passed"], "line 3" in open_row["message"]) == (False, True)
        reported = _named(one, check)
        assert (reported["passed"], "line 4" in reported["message"], one["score"]) == (False, True, 75)
        assert _named(_imports_under(tmp_path, source, lines=[3, 4]), check)["passed"] is True
        assert _named(_imports_under(tmp_path, source, functions=[FILE_SCOPE]), check)["passed"] is True

    def test_handler_independence_reports_the_first_open_line(self, tmp_path):
        source = '"""Doc."""\nfrom aipass.mybr.apps.modules.a import x\nfrom aipass.mybr.apps.modules.b import y\n'
        rel = "mybr/apps/handlers/h.py"
        assert "line 2" in _named(_imports_under(tmp_path, source, rel), "Handler independence")["message"]
        one = _named(_imports_under(tmp_path, source, rel, lines=[2]), "Handler independence")
        assert (one["passed"], "line 3" in one["message"]) == (False, True)
        assert _named(_imports_under(tmp_path, source, rel, functions=[FILE_SCOPE]), "Handler independence")["passed"]

    def test_bare_imports_name_only_the_open_sites(self, tmp_path):
        source = '"""Doc."""\nfrom handlers.x import y\nfrom modules.z import w\n'
        assert _named(_imports_under(tmp_path, source), "No bare imports")["message"].count("Line ") == 2
        one = _named(_imports_under(tmp_path, source, lines=[2]), "No bare imports")
        assert (one["passed"], one["message"].startswith("Line 3:"), "Line 2" in one["message"]) == (False, True, False)
        assert _named(_imports_under(tmp_path, source, functions=[FILE_SCOPE]), "No bare imports")["passed"] is True

    def test_prax_logger_sites_are_the_log_lines_inside_their_functions(self, tmp_path):
        source = '"""Doc."""\nimport logging\n\nlogging.info("a")\n\n\ndef work():\n    logging.info("b")\n' + _FILLER

        def message(**scope):
            return _named(_imports_under(tmp_path, source, **scope), "Prax logger")["message"]

        assert "lines [4, 8]" in message()
        assert "lines [4]:" in message(functions=["work"])
        assert "lines [8]:" in message(lines=[4])
        assert "lines [8]:" in message(functions=[FILE_SCOPE])
        assert _named(_imports_under(tmp_path, source, lines=[4, 8]), "Prax logger")["passed"] is True

    def test_import_order_is_file_level_a_file_scope_row_waives_it_and_a_line_row_does_not(self, tmp_path):
        source = '"""Doc."""\nfrom aipass.prax import logger\nimport os\n'
        assert _named(_imports_under(tmp_path, source), "Import order")["passed"] is False
        assert _named(_imports_under(tmp_path, source, lines=[2, 3]), "Import order")["passed"] is False
        waived = _named(_imports_under(tmp_path, source, functions=[FILE_SCOPE]), "Import order")
        assert (waived["passed"], FILE_SCOPE in waived["message"]) == (True, True)

    def test_a_whole_file_row_still_waives_every_finding(self, tmp_path):
        source = '"""Doc."""\nfrom aipass.prax import logger\nimport os\nA = os.environ["AIPASS_ROOT"]\n'
        result = _imports_under(tmp_path, source, lines=None)
        assert (result["score"], result["checks"][0]["name"]) == (100, "Bypassed")

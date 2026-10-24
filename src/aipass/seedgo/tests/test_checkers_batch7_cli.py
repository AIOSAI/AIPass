# =================== AIPass ====================
# Name: test_checkers_batch7_cli.py
# Description: cli_check rulings: relays, the pre-console window, the stream ruling (split from test_checkers_batch7.py)
# Version: 1.1.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/aipass_standards/cli_check.py and cli_content.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import ast

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import cli_check
from aipass.seedgo.apps.handlers.aipass_standards.cli_check import check_handler_separation
from aipass.seedgo.apps.handlers.aipass_standards.cli_content import get_cli_standards

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestCliCheckAllowsRelayingACapturedSubprocessStream:
    """A router passing a child's bytes through is not "your output, undecorated"."""

    def _lines(self, source):
        """Raw-write lines check_print_usage reports ([] for none). Mutant: raw-write rule bypassed in cli_check.py — killed."""
        result = cli_check.check_print_usage(source, source.splitlines())
        if result is None or "sys.stdout/stderr.write()" not in result["message"]:
            return []
        return ast.literal_eval(result["message"].rsplit(" on lines ", 1)[1].rstrip("."))

    def test_relaying_captured_stdout_attribute_is_allowed(self):
        assert self._lines("        sys.stdout.write(result.stdout)") == []

    def test_relaying_captured_stdout_subscript_is_allowed(self):
        assert self._lines('        sys.stdout.write(result["stdout"])') == []

    def test_relaying_captured_stderr_to_stderr_is_allowed(self):
        assert self._lines("        sys.stderr.write(result.stderr)") == []

    def test_a_literal_is_still_a_violation(self):
        assert self._lines('        sys.stdout.write("hello")') != []

    def test_an_fstring_is_still_a_violation(self):
        assert self._lines('        sys.stdout.write(f"{count} done")') != []

    def test_a_value_you_built_is_still_a_violation(self):
        assert self._lines("        sys.stdout.write(rendered_table)") != []

    def test_crossed_streams_stay_a_violation(self):
        """Captured stderr written to stdout is a routing bug, not a relay."""
        assert self._lines("        sys.stdout.write(result.stderr)") != []
        assert self._lines('        sys.stderr.write(result["stdout"])') != []

    def test_a_commented_out_relay_is_not_examined_at_all(self):
        assert self._lines("        # sys.stdout.write(result.stdout)") == []

    def test_a_commented_out_violation_is_not_flagged(self):
        """The relay case above is inert either way — a mutant that stopped
        stripping comments survived it. This one only passes if comments are actually stripped."""
        assert self._lines('        pass  # sys.stdout.write("hello")') == []

    def test_a_trailing_comment_does_not_hide_a_real_violation(self):
        assert self._lines('        sys.stdout.write("hello")  # relay') != []


class TestCliAllowsARawWriteBeforeTheConsoleExists:
    """@commons' second finding, the same block one line down: the CLI checker
    demanded ``console.print()`` before the module imports the console."""

    CONSOLE_IMPORT = "from aipass.cli.apps.modules import console\n"

    def _passed(self, tmp_path, source):
        target = tmp_path / "modules" / "probe.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        result = cli_check.check_print_usage(source, source.split("\n"), str(target))
        return result is None or result["passed"]

    def test_a_write_above_the_console_import_is_allowed(self, tmp_path):
        source = "import sys\n\nsys.stderr.write('bootstrap trouble\\n')\n\n" + self.CONSOLE_IMPORT
        assert self._passed(tmp_path, source) is True

    def test_a_write_below_the_console_import_keeps_its_finding(self, tmp_path):
        """The window closes at the import. Everything after it has Rich."""
        source = "import sys\n\n" + self.CONSOLE_IMPORT + "\nsys.stderr.write('late\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_write_on_the_import_line_itself_keeps_its_finding(self, tmp_path):
        """The boundary, pinned because a mutant walked through it."""
        source = "import sys\n\n" + self.CONSOLE_IMPORT.rstrip("\n") + "; sys.stderr.write('same line\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_a_module_that_never_imports_the_console_keeps_its_finding(self, tmp_path):
        """Clause 1, pinned as a REFUSAL. Dropping it looks like a
        simplification, and would hand every console-less module a blanket pass."""
        source = "import sys\n\nsys.stderr.write('no console anywhere in this file\\n')\n"
        assert self._passed(tmp_path, source) is False

    def test_an_unparseable_file_gets_no_window(self, tmp_path):
        """Ignorance is not evidence of a bootstrap: a file the checker cannot
        parse keeps every finding rather than being exempted by the failure."""
        source = "import sys\n\nsys.stderr.write('early\\n')\n\n" + self.CONSOLE_IMPORT + "def broken(:\n"
        assert self._passed(tmp_path, source) is False

    def test_the_real_reported_shape_clears(self, tmp_path):
        """@commons' entry point, transcribed: the sys.path repair, its stderr
        report, then the cross-branch imports the repair exists to make safe."""
        source = (
            "import sys\n"
            "from pathlib import Path\n\n"
            "_script_dirs = [str(Path(__file__).parent)]\n"
            "try:\n    _script_dirs.append(str(Path(__file__).resolve().parent))\n"
            "except OSError as _exc:\n"
            "    sys.stderr.write('[commons] cannot resolve\\n')\n"
            "for _d in _script_dirs:\n    if _d in sys.path:\n        sys.path.remove(_d)\n\n"
            "from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: E402\n"
            "from aipass.cli.apps.modules import console  # noqa: E402\n"
        )
        assert self._passed(tmp_path, source) is True


class TestHandlerSeparationJudgesTheStreamNotTheSpelling:
    """@flow, 2026-08-31: the cross-branch import fence scored 0 for two
    ``print(..., file=sys.stderr)`` lines: the standard judges the stream, never the spelling."""

    def _sep(self, content):
        return check_handler_separation(content)

    def test_a_stderr_directed_print_is_a_diagnostic_not_display(self):
        content = (
            "import os\n"
            "import sys\n"
            "\n"
            "def _guard(caller_file, import_line):\n"
            "    if os.environ.get('AIPASS_DEBUG_GUARD'):\n"
            "        print(f'[GUARD DEBUG] caller_file = {caller_file}', file=sys.stderr)\n"
            "        print(f'[GUARD DEBUG] import_line = {import_line}', file=sys.stderr)\n"
        )
        assert self._sep(content)["passed"] is True

    def test_a_bare_print_keeps_its_finding(self):
        """Negative control. Without this the clause would read as "prints are
        fine in handlers now", which is the opposite of the ruling."""
        result = self._sep("def show(x):\n    print(x)\n")
        assert result["passed"] is False
        assert "[2]" in result["message"]

    def test_an_explicitly_stdout_directed_print_keeps_its_finding(self):
        """The discriminator is the STREAM. Naming stdout out loud is still
        display — arguably more so, since the author chose it."""
        assert self._sep("import sys\n\ndef show(x):\n    print(x, file=sys.stdout)\n")["passed"] is False

    def test_a_print_to_some_other_file_handle_keeps_its_finding(self):
        """A write to a handle nobody is watching is not a diagnostic. Same
        clause as silent_catch: ``.write`` reports only when written to a standard stream."""
        assert self._sep("def dump(x, fh):\n    print(x, file=fh)\n")["passed"] is False

    def test_only_the_file_keyword_directs_a_stream(self):
        """Mutation control (M3, survived the first run). Loosening the keyword
        check to accept ``sep`` exempted ``print(x, sep=sys.stderr)``, which still writes to stdout."""
        assert self._sep("import sys\n\ndef show(x):\n    print(x, sep=sys.stderr)\n")["passed"] is False

    def test_a_file_holding_both_keeps_the_finding_and_names_only_the_display_lines(self):
        """The exempted line must not shift the reported line numbers, or the
        finding sends its owner to the wrong place."""
        content = (
            "import sys\n"
            "\n"
            "def report(x):\n"
            "    print('to the user', x)\n"
            "    print('diagnostic', file=sys.stderr)\n"
            "    print('also to the user', x)\n"
        )
        result = self._sep(content)
        assert result["passed"] is False
        assert "[4, 6]" in result["message"]

    def test_an_unparseable_file_keeps_every_print_finding(self):
        """Ignorance is not evidence. A file whose AST cannot be built has no
        stderr-directed prints PROVEN, so none are exempted."""
        result = self._sep("import sys\ndef broken(:\n    print('x', file=sys.stderr)\n")
        assert result["passed"] is False

    def test_the_two_real_fleet_files_now_agree(self):
        """End-to-end against the live tree, because the whole finding was that
        two spellings of one effect disagreed by 100 points."""
        from pathlib import Path

        aipass_root = Path(__file__).resolve().parents[2]
        assert aipass_root.name == "aipass", aipass_root
        stream_write = aipass_root / "skills" / "apps" / "handlers" / "module_paths.py"
        stream_print = aipass_root / "flow" / "apps" / "handlers" / "__init__.py"
        assert stream_write.exists() and stream_print.exists()

        written = cli_check.check_module(str(stream_write))
        printed = cli_check.check_module(str(stream_print))
        assert written["score"] == 100
        assert printed["score"] == written["score"], [c["message"] for c in printed["checks"] if not c["passed"]]


class TestCliReadsCodeLinesAndNeverDocstrings:
    """Handler separation and print usage judge code lines; a docstring is prose whatever it names."""

    def test_a_print_after_a_docstring_quoting_the_other_delimiter_is_found(self):
        result = check_handler_separation('"""Uses \'\'\' quoting."""\nprint("x")\n')
        assert result["message"].startswith("Handler contains print() on lines [2]")

    def test_a_print_of_a_triple_quoted_literal_is_found(self):
        result = check_handler_separation('def f():\n    print("""hello""")\n')
        assert result["message"].startswith("Handler contains print() on lines [2]")

    def test_print_usage_ignores_a_one_line_docstring_naming_print(self):
        source = '"""Never print("x") here."""\nconsole.print("ok")\n'
        result = cli_check.check_print_usage(source, source.split("\n"))
        assert result is not None
        assert result["passed"] is True

    def test_print_usage_ignores_a_multi_line_docstring_naming_print(self):
        source = 'def f():\n    """Avoid\n    print("x") here.\n    """\n    console.print("ok")\n'
        result = cli_check.check_print_usage(source, source.split("\n"))
        assert result is not None
        assert result["passed"] is True

    def test_a_print_after_a_hash_in_a_string_or_after_a_colon_is_found(self):
        source = 'x = "#"; print(x)\n'
        result = cli_check.check_print_usage(source, source.split("\n"))
        assert result is not None
        assert result["passed"] is False
        assert check_handler_separation("def f(ok):\n    if ok: print('hi')\n")["passed"] is False


class TestTheCliRulingsAreQueryableNotJustEnforced:
    """@commons, 2026-08-31: "it currently lives in a docstring nobody queries,
    The rulings are published as a standard a branch can query before hitting the wall."""

    def _content(self):
        return get_cli_standards()

    def test_the_pre_console_window_is_published_with_its_boundary(self):
        content = self._content()
        assert "pre-console bootstrap window" in content
        assert "STRICTLY prior" in content

    def test_the_stream_ruling_is_published_with_both_spellings(self):
        content = self._content()
        assert "print(msg, file=sys.stderr)" in content
        assert "sys.stderr.write(msg)" in content
        assert "print(msg, file=sys.stdout)" in content

    def test_the_published_rule_and_the_checker_agree(self):
        """The point of publishing is that a branch reading it gets the same
        answer the audit gives, over the exact snippets the standard shows."""
        allowed = "import sys\n\ndef f(msg):\n    print(msg, file=sys.stderr)\n"
        refused = "import sys\n\ndef f(msg):\n    print(msg, file=sys.stdout)\n"
        assert check_handler_separation(allowed)["passed"] is True
        assert check_handler_separation(refused)["passed"] is False

# =================== META ====================
# Name: test_stdlib_patch_check.py
# Description: stdlib_patch_check — crack class Q, a patch that replaces work the product owns
# Version: 1.2.0
# Created: 2026-09-22
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/stdlib_patch_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and the target are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs, stdlib_patch_check
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: The package holding @backup's ceiling, which test_ceiling_guard.py:103 reaches os.path through.
CEILING = "aipass.backup.apps.handlers.scan"

#: @ai_mail's real module whose LAST segment is the name of a stdlib package.
COLLIDING = "aipass.ai_mail.apps.modules.email"

#: @backup's own module, which says `from pathlib import Path` — the specimen's home.
UPLOAD = "aipass.backup.apps.handlers.drive"

#: A module that both imports Path AND defines a class: one file, both verdicts.
WATCHDOG = "aipass.devpulse.apps.handlers.watchdog"

#: @backup's package whose sibling import `from ..json import json_handler` reads as stdlib json.
RELATIVE = "aipass.backup.apps.handlers.project"


def _scored(source):
    """Just the (line, target, module) rows this rule charges."""
    return stdlib_patch_check.scan(source)[0]


def _unresolved(source):
    """How many targets the AST could not resolve, reported and charged to nobody."""
    return stdlib_patch_check.scan(source)[1]


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_charges_nothing(self):
        """tests/test_readme_update.py patches only product code."""
        assert _scored(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert stdlib_patch_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """test_ceiling_guard.py:103 — patch.object(ceiling.os.path, 'getsize')."""

    def test_a_stdlib_reached_through_a_product_module_is_convicted(self):
        """ceiling.os IS the real os: patching it replaces getsize process-wide."""
        source = f"from {CEILING} import ceiling\ndef test_it():\n    patch.object(ceiling.os.path, 'getsize')\n"
        assert _scored(source) == [(3, "ceiling.os.path", "os")]

    def test_a_directly_imported_stdlib_module_is_convicted(self):
        """The plainer spelling, same replacement."""
        source = "import shutil\ndef test_it():\n    patch.object(shutil, 'copy2')\n"
        assert _scored(source) == [(3, "shutil", "shutil")]

    def test_a_dotted_string_target_is_convicted(self):
        """patch('time.time') needs no import to resolve — the string says it."""
        assert _scored("def test_it():\n    patch('time.time')\n") == [(2, "time.time", "time")]

    def test_monkeypatch_setattr_is_the_third_spelling(self):
        """patch, patch.object and monkeypatch.setattr all replace a name."""
        source = "import shutil\ndef test_it(monkeypatch):\n    monkeypatch.setattr(shutil, 'rmtree', fake)\n"
        assert _scored(source) == [(3, "shutil", "shutil")]


class TestTheAcquittedSeams:
    """The sanctioned set, drawn on the edge/own-work line and listed in the docs."""

    @pytest.mark.parametrize("module", ["subprocess", "socket", "urllib", "asyncio"])
    def test_an_outer_edge_is_a_seam_a_test_should_seal(self, module):
        """No product-local seam would serve better than sealing the process edge."""
        source = f"import {module}\ndef test_it():\n    patch.object({module}, 'run')\n"
        assert _scored(source) == []

    @pytest.mark.parametrize("target", ["sys.argv", "sys.stdout", "os.environ", "sys.modules", "sys.meta_path"])
    def test_the_interpreters_own_tables_are_seams(self, target):
        """argv, the streams, the import tables and the environment are process state."""
        assert _scored(f"def test_it():\n    patch('{target}')\n") == []

    @pytest.mark.parametrize(
        "call",
        [
            'patch.object(sys, "argv", ["x"])',
            'monkeypatch.setattr(sys, "argv", ["x"])',
            "patch.object(sys, 'meta_path', [])",
        ],
    )
    def test_the_object_spellings_of_a_table_are_the_same_seam(self, call):
        """The object and its attribute named apart are judged as the string form."""
        assert _scored(f"import sys\ndef test_it(monkeypatch):\n    {call}\n") == []

    @pytest.mark.parametrize("call", ['patch.object(sys, "exit")', 'monkeypatch.setattr(sys, "platform", "win32")'])
    def test_the_rest_of_sys_is_still_convicted_in_the_object_spelling(self, call):
        """The control: an attribute outside the tables still scores, so the cure did not open sys."""
        assert _scored(f"import sys\ndef test_it(monkeypatch):\n    {call}\n") == [(3, "sys", "sys")]

    def test_product_code_is_not_this_rules_business(self):
        """A seam in aipass is exactly what the cure asks for."""
        source = f"from {CEILING} import ceiling\ndef test_it():\n    patch.object(ceiling, 'measure')\n"
        assert _scored(source) == []


class TestTheNameCollisionDefence:
    """One module named email cost 291 false convictions before the disk check."""

    def test_a_product_module_named_for_a_stdlib_package_is_acquitted(self):
        """aipass...modules.email is @ai_mail's own code, not stdlib email."""
        source = f"import {COLLIDING} as mail\ndef test_it():\n    patch.object(mail.send, 'now')\n"
        assert _scored(source) == []

    def test_is_product_module_asks_the_filesystem_not_the_name(self):
        """Only the disk can tell a collision from the real thing."""
        assert stdlib_patch_check.is_product_module(COLLIDING) is True
        assert stdlib_patch_check.is_product_module("aipass.no_such_branch.apps") is False

    def test_the_boundary_is_the_first_segment_that_is_not_product_code(self):
        """ceiling.os is where aipass ends and the stdlib begins, one segment earlier."""
        source = f"from {CEILING} import ceiling\ndef test_it():\n    patch.object(ceiling.os, 'remove')\n"
        assert _scored(source) == [(3, "ceiling.os", "os")]


class TestAStdlibClassReachedThroughAProductBinding:
    """@backup's finding, 2026-09-23: the same replacement, spelled two ways."""

    def test_backups_exact_form_is_convicted(self):
        """monkeypatch.setattr(product_module.Path, 'resolve') — the specimen."""
        body = "def test_it(monkeypatch):\n    monkeypatch.setattr(upload.Path, 'resolve', fake)\n"
        assert _scored(f"from {UPLOAD} import upload\n{body}") == [(3, "upload.Path", "pathlib")]

    def test_the_two_spellings_reach_the_same_verdict(self):
        """Which name reached the class cannot change what the class IS."""
        body = "def test_it(monkeypatch):\n    monkeypatch.setattr(upload.Path, 'resolve', fake)\n"
        binding = _scored(f"from {UPLOAD} import upload\n{body}")
        string = _scored("def test_it():\n    patch('pathlib.Path.resolve')\n")
        assert [row[2] for row in binding] == [row[2] for row in string] == ["pathlib"]

    def test_a_class_the_product_module_defines_is_acquitted(self):
        """agent.TranscriptScanner is @devpulse's own: patching it is the cure, not the defect."""
        body = "def test_it(monkeypatch):\n    monkeypatch.setattr(agent.TranscriptScanner, 'tick', fake)\n"
        assert _scored(f"from {WATCHDOG} import agent\n{body}") == []

    def test_a_name_the_module_imported_from_aipass_is_acquitted(self):
        """agent.py says `from aipass.devpulse...json import json_handler` — product, not stdlib."""
        body = "def test_it():\n    patch.object(agent.json_handler, 'read')\n"
        assert _scored(f"from {WATCHDOG} import agent\n{body}") == []

    def test_one_module_answers_both_ways(self):
        """The same file imports Path and defines TranscriptScanner — the discriminator is the import."""
        assert stdlib_patch_check.bound_to(f"{WATCHDOG}.agent", "Path") == "pathlib.Path"
        assert stdlib_patch_check.bound_to(f"{WATCHDOG}.agent", "TranscriptScanner") == ""

    def test_a_sibling_package_named_for_a_stdlib_module_is_acquitted(self):
        """`from ..json import json_handler` is relative, and a relative import is never stdlib."""
        body = "def test_it():\n    patch.object(config.json_handler, 'read')\n"
        assert _scored(f"from {RELATIVE} import config\n{body}") == []


class TestWhatItRefusesToJudge:
    """The honest edge of a resolution-based rule, bigger than what it convicts."""

    def test_a_locally_bound_target_is_reported_not_charged(self):
        """mod = importlib.import_module(...) — the AST cannot say what mod is."""
        source = "def test_it():\n    patch.object(mod.os.path, 'getsize')\n"
        assert _scored(source) == []
        assert _unresolved(source) == 1

    def test_a_patch_with_no_target_is_ignored(self):
        """patch() with no argument is a syntax problem, not a judgement."""
        assert stdlib_patch_check.scan("def test_it():\n    patch()\n") == ([], 0)

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert stdlib_patch_check.scan("def test_it(:\n") == ([], 0)

    def test_a_product_module_that_does_not_parse_is_not_judged_not_acquitted(self, tmp_path, monkeypatch):
        """An import list nobody could read says nothing about what Path is."""
        package = tmp_path / "aipass" / "zz_leg15_specimen"
        package.mkdir(parents=True)
        (tmp_path / "aipass" / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "broken.py").write_text("from pathlib import Path\ndef x(:\n", encoding="utf-8")
        monkeypatch.setattr(stdlib_patch_check, "_source_root", lambda: tmp_path)
        body = "def test_it(monkeypatch):\n    monkeypatch.setattr(broken.Path, 'resolve', fake)\n"
        source = f"from aipass.zz_leg15_specimen import broken\n{body}"
        assert stdlib_patch_check.scan(source) == ([], 1)


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "import shutil\ndef test_it():\n    patch.object(shutil, 'copy2')\n")
        assert stdlib_patch_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = stdlib_patch_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_the_unresolved_count_rides_in_the_passing_message(self, tmp_path):
        """The number rides along without becoming a verdict."""
        path = _write(tmp_path, "def test_it():\n    patch.object(mod.os.path, 'getsize')\n")
        result = stdlib_patch_check.check_module(str(path))
        assert result["score"] == 100
        assert "1 locally-bound target could not be resolved" in result["checks"][0]["message"]

    def test_a_file_with_nothing_unresolved_reads_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = stdlib_patch_check.check_module(str(path))["checks"][0]["message"]
        assert message == "Every patch here targets product code or an edge worth sealing"

    def test_the_message_names_the_module_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, "import shutil\ndef test_it():\n    patch.object(shutil, 'copy2')\n")
        message = stdlib_patch_check.check_module(str(path))["checks"][0]["message"]
        assert "replaces shutil process-wide" in message
        assert stdlib_patch_check.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one patch and '(+1 more)'."""
        body = "def test_a():\n    patch('time.time')\ndef test_b():\n    patch('json.dump')\n"
        checks = stdlib_patch_check.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(stdlib_patch_check.CURE) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_it():\n    patch('time.time')\n")

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — stdlib_patch" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code calling os.path is not patching anything."""
        assert stdlib_patch_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A patch's verdict belongs on the file that writes it."""
        assert stdlib_patch_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "stdlib_patch"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    patch('time.time')\n")
        assert (
            stdlib_patch_check.check_module(
                str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )


class TestALineRuleAcquitsItsLineAlone:
    """A rule with ``lines`` acquits those rows and no others (seedgo, fleet green leg 16)."""

    BODY = "def test_a():\n    patch('time.time')\ndef test_b():\n    patch('json.dump')\n"

    def _message(self, tmp_path, lines):
        """What check_module says under a rule naming *lines* of the two-patch file."""
        path = _write(tmp_path, self.BODY)
        rule = {"standard": "stdlib_patch", "file": str(path), "lines": lines}
        return stdlib_patch_check.check_module(str(path), bypass_rules=[rule])["checks"][0]["message"]

    def test_a_rule_naming_one_hit_leaves_the_other(self, tmp_path):
        """Two scored patches at lines 2 and 4; a rule for 2 leaves only 4."""
        said = self._message(tmp_path, [2])

        assert said == f"test_specimen.py:4 json.dump replaces json process-wide - {stdlib_patch_check.CURE}"

    def test_a_rule_naming_every_hit_passes_the_file(self, tmp_path):
        """With both rows acquitted nothing is left to charge."""
        path = _write(tmp_path, self.BODY)
        rule = {"standard": "stdlib_patch", "file": str(path), "lines": [2, 4]}

        assert stdlib_patch_check.check_module(str(path), bypass_rules=[rule])["score"] == 100

    def test_a_rule_naming_a_line_that_is_no_hit_changes_nothing(self, tmp_path):
        """Line 3 holds no patch: both rows stay charged."""
        said = self._message(tmp_path, [3])

        assert said.count(stdlib_patch_check.CURE) == 2
        assert said.startswith("test_specimen.py:2 time.time replaces time process-wide")


class TestAnFStringTargetWithAModuleConstantHead:
    """``patch(f"{_MOD}.shutil.which")`` was unresolved, counted and never judged (seedgo, fleet green leg 17)."""

    HEAD = f'_MOD = "{WATCHDOG}.agent"\n'

    def test_a_stdlib_tail_is_scored_as_the_test_wrote_it(self):
        """The same verdict the constant form gets, at the call's line."""
        body = 'def test_it():\n    patch(f"{_MOD}.Path.resolve")\n'

        assert _scored(self.HEAD + body) == [(3, 'f"{_MOD}.Path.resolve"', "pathlib")]

    def test_a_product_tail_is_acquitted_like_the_constant_form(self):
        """agent.TranscriptScanner is the product's own class: nothing scored, nothing unread."""
        source = self.HEAD + 'def test_it():\n    patch(f"{_MOD}.TranscriptScanner.tick")\n'

        assert stdlib_patch_check.scan(source) == ([], 0)

    def test_a_head_bound_inside_the_function_stays_unresolved(self):
        """A local name is not the module's constant: counted, never guessed."""
        source = f'def test_it():\n    _MOD = "{WATCHDOG}.agent"\n    patch(f"{{_MOD}}.Path.resolve")\n'

        assert stdlib_patch_check.scan(source) == ([], 1)

    def test_a_head_bound_twice_at_module_level_stays_unresolved(self):
        """Two bindings, two possible strings: counted, never guessed."""
        source = self.HEAD + '_MOD = "os"\ndef test_it():\n    patch(f"{_MOD}.Path.resolve")\n'

        assert stdlib_patch_check.scan(source) == ([], 1)

    def test_two_fields_are_joined_in_order(self):
        """Constant parts and fields keep their order: '{_A}.{_B}' is not '{_B}.{_A}'."""
        source = f'_A = "{WATCHDOG}"\n_B = "agent.Path"\ndef test_it():\n    patch(f"{{_A}}.{{_B}}.resolve")\n'

        assert _scored(source) == [(4, 'f"{_A}.{_B}.resolve"', "pathlib")]

    @pytest.mark.parametrize(
        "line",
        ["from aipass.hooks.tests.support_specimen import _MOD", "from .support_specimen import _MOD"],
    )
    def test_a_head_imported_from_the_branchs_own_support_module_is_scored(self, tmp_path, line):
        """hooks' split moved _MOD into support_session_boot.py and 45 execvp/kill sites went unjudged."""
        tests_dir = tmp_path / "hooks" / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "support_specimen.py").write_text(self.HEAD, encoding="utf-8")
        path = tests_dir / "test_specimen.py"
        source = line + '\ndef test_it():\n    patch(f"{_MOD}.Path.resolve")\n'
        path.write_text(source, encoding="utf-8")

        said = stdlib_patch_check.check_module(str(path))["checks"][0]["message"]
        assert said.startswith('test_specimen.py:3 f"{_MOD}.Path.resolve" replaces pathlib process-wide')

    @pytest.mark.parametrize(
        "line",
        [
            "from aipass.flow.tests.support_specimen import _MOD",
            "from aipass.hooks.tests.helpers_specimen import _MOD",
            "from .support_specimen import _MOD\n_MOD = 'os'",
        ],
    )
    def test_another_branch_a_non_support_module_or_a_rebound_name_stays_unresolved(self, tmp_path, line):
        tests_dir = tmp_path / "hooks" / "tests"
        tests_dir.mkdir(parents=True)
        for stem in ("support_specimen", "helpers_specimen"):
            (tests_dir / f"{stem}.py").write_text(self.HEAD, encoding="utf-8")
        path = tests_dir / "test_specimen.py"
        source = line + '\ndef test_it():\n    patch(f"{_MOD}.Path.resolve")\n'
        path.write_text(source, encoding="utf-8")

        assert stdlib_patch_check.scan(source, path) == ([], 1)

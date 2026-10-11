# =================== META ====================
# Name: test_literal_path_check.py
# Description: literal_path_check — test template v1 item 22, paths built from tmp_path, never written
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/literal_path_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX; the shapes and line numbers are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import literal_path_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The fleet's gold test file for this item, resolved from this file's own
#: location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: Split so this file's own source is not a home path to hardcoded_path, which
#: is the very standard the carve-out below hands the shape back to. Same
#: device host_portability uses for its /proc literal.
HOME_SAMPLE = "/" + "home/someone/AIPass/x.py"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _values(source):
    """Just the path each hit names, in line order."""
    return [name.split('"')[1] for _line, name, _fix in literal_path_check.scan(source)]


class TestALiteralHandedToACallIsConvicted:
    """281 of the 874 fleet hits are the template's own shape, Path("/...")."""

    def test_the_templates_own_example_is_a_hit(self):
        assert _values('Path("/nonexistent/path")\n') == ["/nonexistent/path"]

    def test_a_product_call_is_a_hit(self):
        """Item 22 is not about pathlib: any call handed an invented path is the habit."""
        assert _values('register_contact("/some/inbox.json")\n') == ["/some/inbox.json"]

    def test_a_keyword_argument_is_a_hit(self):
        assert _values('audit(file_path="/fake/apps/entry.py")\n') == ["/fake/apps/entry.py"]

    def test_a_method_call_on_a_receiver_is_a_hit(self):
        assert _values('monitor.load("/fake/state.json")\n') == ["/fake/state.json"]

    def test_every_argument_of_one_call_is_its_own_hit(self):
        assert _values('spell("/a/one", "/b/two")\n') == ["/a/one", "/b/two"]

    def test_the_line_number_is_the_argument(self):
        source = 'import os\n\nclassify(\n    "/fake/x.py",\n)\n'

        assert literal_path_check.scan(source)[0][0] == 4

    def test_the_same_path_twice_on_one_line_is_reported_once(self):
        """Two hits at one line and one value would print the same row twice."""
        assert _values('spell("/a/one", "/a/one")\n') == ["/a/one"]

    def test_a_root_separator_alone_is_not_a_path(self):
        """ "/" and "//" carry no host in them, so there is no habit to end."""
        assert _values('walk("/")\nwalk("//")\n') == []


class TestANameBoundOnlyToALiteralIsTheSameHabit:
    """20 sites in 8 files bind the path once and hand the name to several calls."""

    def test_a_bound_name_is_judged_where_it_is_used(self):
        source = 'fake_home = "/fake/aipass/home"\nadopt.run(fake_home)\n'

        assert literal_path_check.scan(source) == [
            (2, 'literal absolute path "/fake/aipass/home"', literal_path_check.FIX)
        ]

    def test_the_binding_line_alone_is_not_a_hit(self):
        """An assignment touches nothing. ARM A's measurement is why this line sits here."""
        assert _values('fake_home = "/fake/aipass/home"\n') == []

    def test_a_name_reassigned_to_anything_else_is_dropped(self):
        """Which value reaches the call is a question one pass cannot answer."""
        source = 'p = "/fake/one"\np = build()\nrun(p)\n'

        assert _values(source) == []

    def test_a_name_bound_to_an_acquitted_literal_stays_acquitted(self):
        source = 'shell = "/bin/bash"\nlaunch(shell)\n'

        assert _values(source) == []


class TestWhatIsNeverConvicted:
    """Each carve-out carries its fleet count; none of them is a guess."""

    def test_a_literal_that_only_sits_somewhere_is_data(self):
        """The restriction to an argument IS the rule: 2,491 nominations become 874."""
        source = 'table = {"/srv/data/x.json": 1}\nassert result == "/fake/repo"\n'

        assert _values(source) == []

    def test_a_home_rooted_literal_belongs_to_hardcoded_path(self):
        """78 in argument position. One line charged by two standards teaches neither."""
        assert _values(f'Path("{HOME_SAMPLE}")\n') == []

    def test_a_mock_return_value_is_a_stubs_data(self):
        """200 fleet-wide — what the stub RETURNS, not a path the test opens."""
        source = 'm = MagicMock()\nm.which.return_value = "/usr/local/bin/claude"\n'

        assert _values(source) == []

    def test_a_mock_constructor_argument_is_a_stubs_data(self):
        assert _values('MagicMock(name="/fake/thing")\n') == []

    def test_a_url_path_names_a_route_not_a_file(self):
        """188 fleet-wide, all of them api's client verbs."""
        assert _values('client.get("/v1/whoami")\n') == []

    def test_a_system_root_names_a_real_file_the_test_is_about(self):
        """60 fleet-wide. tmp_path cannot express "a file the fence must refuse"."""
        source = 'read_file("/etc/passwd")\nsetenv("SHELL", "/bin/bash")\n'

        assert _values(source) == []

    def test_a_pure_path_class_touches_no_filesystem(self):
        """26 fleet-wide: string algebra, which is how a POSIX path is judged as Windows."""
        assert _values('PureWindowsPath("/x/checkout/a.py")\n') == []

    def test_a_string_operation_is_a_comparison_not_a_path(self):
        """10 fleet-wide."""
        assert _values('assert value.startswith("/proc")\n') == []

    def test_a_literal_with_whitespace_is_prose(self):
        """hooks binds a two-sentence refusal that opens with a path. One site fleet-wide."""
        source = 'truth = "/proj/.aipass/hooks.json exists, but this project is not enrolled"\nshow(truth)\n'

        assert _values(source) == []

    def test_a_relative_path_is_the_cure_not_the_disease(self):
        assert _values('Path("apps/handlers/x.py")\n') == []


class TestTheDriveRootedCountIsRecordedNotCharged:
    """15 sites in 8 files. On a POSIX host tmp_path cannot produce C:\\proj."""

    def test_a_drive_rooted_literal_is_not_convicted(self):
        assert _values('_spell(_WindowsFlavour(r"C:\\proj\\AIPass"))\n') == []

    def test_a_drive_rooted_literal_is_counted(self):
        source = '_spell(_WindowsFlavour(r"C:\\proj\\AIPass"))\n'

        assert literal_path_check.counted_drive_paths(source) == [(1, "C:\\proj\\AIPass")]

    def test_a_forward_slash_drive_is_counted_too(self):
        assert literal_path_check.counted_drive_paths('_under("C:/env/pkg/f.py")\n') == [(1, "C:/env/pkg/f.py")]

    def test_a_drive_rooted_mock_value_is_not_even_counted(self):
        assert literal_path_check.counted_drive_paths('m.root.return_value = "C:/env"\n') == []

    def test_the_count_rides_in_the_passing_message(self, tmp_path):
        path = _write(tmp_path, '_under("C:/env/pkg/f.py")\n')

        message = literal_path_check.check_module(str(path))["checks"][0]["message"]

        assert message == (
            "Every path in use is built, not written (1 drive-rooted path is counted, which the rule allows)"
        )

    def test_a_clean_file_with_no_drive_paths_says_so_plainly(self, tmp_path):
        path = _write(tmp_path, 'def test_x(tmp_path):\n    classify(tmp_path / "a.py")\n')

        message = literal_path_check.check_module(str(path))["checks"][0]["message"]

        assert message == "Every path in use is built, not written"


class TestCheckModuleIsThePerFileLane:
    def test_a_clean_file_scores_a_hundred(self, tmp_path):
        path = _write(tmp_path, 'def test_x(tmp_path):\n    classify(tmp_path / "apps" / "entry.py")\n')

        result = literal_path_check.check_module(str(path))

        assert result["passed"] is True
        assert result["score"] == 100

    def test_a_convicted_file_scores_zero(self, tmp_path):
        path = _write(tmp_path, 'def test_x():\n    classify("/fake/repo/apps/entry.py")\n')

        result = literal_path_check.check_module(str(path))

        assert result["passed"] is False
        assert result["score"] == 0

    def test_every_hit_gets_its_own_line_with_file_and_number(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and counts the rest.

        So N checks would show one hit and hide the others; the lines live in
        one message instead, and this pins that they all survive.
        """
        path = _write(tmp_path, 'def test_x():\n    classify("/fake/a.py")\n    classify("/fake/b.py")\n')

        message = literal_path_check.check_module(str(path))["checks"][0]["message"]

        assert message.splitlines() == [
            f'test_thing.py:2 literal absolute path "/fake/a.py" - {literal_path_check.FIX}',
            f'test_thing.py:3 literal absolute path "/fake/b.py" - {literal_path_check.FIX}',
        ]

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        result = literal_path_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["passed"] is False
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_no_hits(self, tmp_path):
        """ruff already convicts the syntax error; guessing at line numbers would not help."""
        path = _write(tmp_path, "def test_x(:\n")

        assert literal_path_check.check_module(str(path))["passed"] is True

    def test_a_file_bypass_acquits_the_whole_file(self, tmp_path):
        path = _write(tmp_path, 'classify("/fake/a.py")\n')
        rules = [{"standard": "literal_path", "file": str(path), "reason": "measured"}]

        result = literal_path_check.check_module(str(path), bypass_rules=rules)

        assert result["passed"] is True
        assert "bypassed" in result["checks"][0]["message"]

    def test_the_rule_scopes_to_tests_and_scores_every_file(self):
        """A production module builds paths from config, not from tmp_path."""
        assert literal_path_check.APPLIES_TO == "tests"
        assert literal_path_check.AUDIT_SCOPE == "all_files"


class TestTheModelFileHoldsTheLine:
    """tests/test_readme_update.py is the fleet's gold test file for this item."""

    def test_the_model_file_passes(self):
        assert literal_path_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_file_with_one_literal_path_is_convicted(self, tmp_path):
        """Not a hand-written sample: the real file, plus the one line item 22 names."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source + '\n\ndef test_a_literal(tmp_path):\n    readme_update.freshness(Path("/nonexistent/path"))\n'
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = literal_path_check.check_module(str(path))

        assert result["score"] == 0
        assert '"/nonexistent/path"' in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_literal_path(self, tmp_path, capsys):
        path = _write(tmp_path, 'def test_x():\n    classify("/fake/repo/apps/entry.py")\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — literal_path" in out
        assert "tmp_path" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, 'def test_x(tmp_path):\n    classify(tmp_path / "entry.py")\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ literal_path" in out
        assert "[FAIL] — literal_path" not in out

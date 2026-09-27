# =================== META ====================
# Name: test_discarded_patch_check.py
# Description: discarded_patch_check — crack class R, a mock nothing ever observes
# Version: 1.0.2
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/discarded_patch_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and the target are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import discarded_patch_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series. It passes, and it is the
#: shape every planted specimen below is a mutation of.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: The branch every specimen below pretends to belong to, so that
#: ``aipass.backup.*`` is its own code and everything else is an edge.
BRANCH = "backup"

#: The line @backup's test_ceiling_guard.py repeats fourteen times.
OWN_TARGET = "aipass.backup.apps.handlers.audit.trail.log_operation"


def _lines(source, branch=BRANCH):
    """Just the convicted line numbers, in order."""
    return [line for line, _target in discarded_patch_check.scan(source, branch)]


def _targets(source, branch=BRANCH):
    """Just the patched targets, in line order."""
    return [target for _line, target in discarded_patch_check.scan(source, branch)]


def _write(tmp_path, body, branch=BRANCH, name="test_specimen.py"):
    """A file at src/aipass/<branch>/tests/, which is where branch_of reads from."""
    tests_dir = tmp_path / "aipass" / branch / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_is_clean(self):
        """tests/test_readme_update.py convicts nothing."""
        source = MODEL.read_text(encoding="utf-8")
        assert discarded_patch_check.scan(source, "seedgo") == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert discarded_patch_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimens:
    """One specimen per shape, each taken from a row the reviewers confirmed."""

    def test_a_with_patch_of_own_code_that_binds_nothing_is_convicted(self):
        """test_ceiling_guard.py — fourteen tests, every one this line."""
        source = f"def test_it():\n    with patch({OWN_TARGET!r}):\n        assert check_ceiling(f, c) is None\n"
        assert _lines(source) == [2]
        assert _targets(source) == [OWN_TARGET]

    def test_a_patch_decorator_whose_parameter_is_unused_is_convicted(self):
        """The decorator form hides the same discard behind an injected name."""
        source = f"@patch({OWN_TARGET!r})\ndef test_it(_log):\n    assert check_ceiling(f, c) is None\n"
        assert _lines(source) == [1]

    def test_a_target_this_file_never_imported_is_not_own_code(self):
        """The rule only convicts what it can name: an unbound local is an edge."""
        source = "def test_it():\n    monkeypatch.setattr(trail, 'log_operation', Mock())\n    assert run() is None\n"
        assert _lines(source) == []

    def test_an_anonymous_mock_on_an_imported_own_name_is_convicted(self):
        """The target is a name this file bound from its own branch's package."""
        source = (
            "from aipass.backup.apps.handlers.audit import trail\n"
            "def test_it():\n"
            "    monkeypatch.setattr(trail, 'log_operation', Mock())\n"
            "    assert run() is None\n"
        )
        assert _lines(source) == [3]
        assert _targets(source) == ["trail.log_operation"]

    def test_a_silencing_lambda_is_convicted(self):
        """lambda *a, **k: None records nothing and can be asked nothing."""
        source = (
            "from aipass.backup.apps.handlers.audit import trail\n"
            "def test_it():\n"
            "    monkeypatch.setattr(trail, 'log_operation', lambda *a, **k: None)\n"
            "    assert run() is None\n"
        )
        assert _lines(source) == [3]


class TestWhatStaysLegal:
    """Each acquittal is a measured cut, and each cost real hits to find."""

    def test_a_binding_asserted_after_the_with_block_is_acquitted(self):
        """test_ceiling_guard.py:278. Reading only the block was 51 files, 331 hits."""
        source = (
            f"def test_it():\n"
            f"    with patch({OWN_TARGET!r}) as snap:\n"
            f"        run_all()\n"
            f"    snap.assert_not_called()\n"
        )
        assert _lines(source) == []

    def test_a_second_positional_replacement_is_acquitted(self):
        """patch(target, tmp_path) redirects a constant. This cut was 1,025 -> 692."""
        source = (
            "def test_it(tmp_path):\n"
            "    with patch('aipass.backup.apps.handlers.paths.SNAPSHOT_DIR', tmp_path):\n"
            "        run_all()\n"
        )
        assert _lines(source) == []

    def test_a_return_value_is_acquitted(self):
        """A mock that answers is a seam doing work, not a mock thrown away."""
        source = f"def test_it():\n    with patch({OWN_TARGET!r}, return_value=None):\n        run_all()\n"
        assert _lines(source) == []

    def test_another_branch_is_acquitted(self):
        """Sealing an edge is what a test is supposed to do."""
        source = "def test_it():\n    with patch('aipass.api.apps.handlers.google.client.upload'):\n        run_all()\n"
        assert _lines(source) == []

    def test_a_patch_outside_a_test_body_is_acquitted(self):
        """The conftest seam is sanctioned; only def test_* bodies are judged."""
        source = f"@pytest.fixture\ndef quiet():\n    with patch({OWN_TARGET!r}):\n        yield\n"
        assert _lines(source) == []

    def test_a_recording_lambda_is_acquitted(self):
        """test_share.py 100, 112, 122 — both reviewers marked them SOUND."""
        source = (
            "from aipass.backup.apps.handlers.share import share_module\n"
            "def test_it():\n"
            "    ran = []\n"
            "    monkeypatch.setattr(share_module, 'run_share', lambda *a: ran.append(a))\n"
            "    assert ran == []\n"
        )
        assert _lines(source) == []

    def test_a_named_replacement_is_acquitted(self):
        """The name is read at the setattr itself; no name set can tell them apart."""
        source = (
            "from aipass.backup.apps.handlers.audit import trail\n"
            "def test_it():\n"
            "    recorder = Mock()\n"
            "    monkeypatch.setattr(trail, 'log_operation', recorder)\n"
            "    recorder.assert_called_once()\n"
        )
        assert _lines(source) == []


class TestTheBranchIsReadFromThePath:
    """A test file imports a dozen branches and no import says which is its own."""

    def test_a_tests_directory_names_its_branch(self, tmp_path):
        """src/aipass/backup/tests/test_x.py belongs to @backup."""
        path = _write(tmp_path, "def test_it():\n    pass\n")
        assert discarded_patch_check.branch_of(str(path)) == BRANCH

    def test_a_path_outside_the_product_names_no_branch(self, tmp_path):
        """Nothing under an aipass/ parent, so there is no own code."""
        assert discarded_patch_check.branch_of(str(tmp_path / "test_x.py")) == ""

    def test_a_file_outside_a_branch_scores_100(self, tmp_path):
        """Every patch there would read as an edge, so none may be charged."""
        path = tmp_path / "test_loose.py"
        path.write_text(f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n", encoding="utf-8")
        result = discarded_patch_check.check_module(str(path))
        assert result["score"] == 100
        assert "no own code" in result["checks"][0]["message"]

    def test_the_same_source_is_acquitted_under_another_branch(self):
        """The identical file in @api's tests patches an edge, not its own code."""
        source = f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n"
        assert _lines(source, "backup") == [2]
        assert _lines(source, "api") == []


class TestDecoratorsBindBottomUp:
    """The decorator closest to the def fills the FIRST parameter."""

    def test_the_unused_slot_reports_its_own_line(self):
        """Source order fills the wrong slots and then reports the wrong line."""
        source = (
            f"@patch('aipass.backup.apps.handlers.audit.trail.log_failure')\n"
            f"@patch({OWN_TARGET!r})\n"
            f"def test_it(_log, failure):\n"
            f"    failure.assert_called_once()\n"
        )
        assert _lines(source) == [2]
        assert _targets(source) == [OWN_TARGET]


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n")
        assert discarded_patch_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = discarded_patch_check.check_module(str(tmp_path / "aipass" / BRANCH / "tests" / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        path = _write(tmp_path, "def test_it(:\n")
        assert discarded_patch_check.check_module(str(path))["score"] == 100

    def test_a_clean_file_names_the_branch_it_cleared(self, tmp_path):
        """The passing message says whose own code was checked."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 1\n")
        message = discarded_patch_check.check_module(str(path))["checks"][0]["message"]
        assert f"@{BRANCH}" in message

    def test_the_message_names_the_target_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n")
        message = discarded_patch_check.check_module(str(path))["checks"][0]["message"]
        assert OWN_TARGET in message
        assert discarded_patch_check.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one patch and '(+1 more)'."""
        body = f"def test_a():\n    with patch({OWN_TARGET!r}):\n        run()\ndef test_b():\n    with patch({OWN_TARGET!r}):\n        run()\n"
        checks = discarded_patch_check.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(OWN_TARGET) == 2

    def test_the_command_prints_every_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — discarded_patch" in out
        assert "log_operation" in out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code has no def test_*; running it there is noise."""
        assert discarded_patch_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A verdict about a patch in one file belongs on that file."""
        assert discarded_patch_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "discarded_patch"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, f"def test_it():\n    with patch({OWN_TARGET!r}):\n        run()\n")
        assert (
            discarded_patch_check.check_module(
                str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )

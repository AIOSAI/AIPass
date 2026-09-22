# =================== META ====================
# Name: test_named_encoding_check.py
# Description: named_encoding_check — test template v1 item 21, encoding named on every text read and write
# Version: 1.0.0
# Created: 2026-09-21
# =============================================

"""Tests for apps/handlers/aipass_standards/named_encoding_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX; the shapes and line numbers are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import named_encoding_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The fleet's gold test file for this item, resolved from this file's own
#: location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _names(source):
    """Just the name strings from a scan, in line order."""
    return [name for _line, name, _fix in named_encoding_check.scan(source)]


class TestPathlibsTwoConvenienceMethodsAreConvicted:
    """703 write_text and 215 read_text hits fleet-wide — the whole of the rule."""

    def test_a_write_text_without_an_encoding_is_a_hit(self):
        assert _names("p.write_text(body)\n") == ["write_text() without encoding"]

    def test_a_read_text_without_an_encoding_is_a_hit(self):
        assert _names("data = p.read_text()\n") == ["read_text() without encoding"]

    def test_a_chained_call_on_a_built_path_is_a_hit(self):
        """The receiver is an expression, not a name — the rule reads the method."""
        source = 'def test_x(tmp_path):\n    (tmp_path / "README.md").write_text("body")\n'

        assert _names(source) == ["write_text() without encoding"]

    def test_every_call_site_is_its_own_hit(self):
        source = 'p.write_text("a")\np.write_text("b")\n'

        assert len(_names(source)) == 2

    def test_the_line_number_is_the_call(self):
        source = 'import os\n\np.write_text("body")\n'

        assert named_encoding_check.scan(source)[0][0] == 3


class TestBuiltinOpenIsConvictedInTextModeOnly:
    def test_an_open_with_no_mode_is_a_hit(self):
        """The default mode is "r", which is text."""
        assert _names("with open(path) as handle:\n    pass\n") == ["open() without encoding"]

    def test_an_open_in_a_text_mode_is_a_hit(self):
        assert _names('handle = open(path, "w")\n') == ["open() without encoding"]

    def test_a_keyword_mode_reads_the_same(self):
        assert _names('handle = open(path, mode="a")\n') == ["open() without encoding"]

    def test_a_binary_mode_is_not_a_hit(self):
        """Bytes have no encoding to name."""
        assert _names('handle = open(path, "rb")\n') == []

    def test_a_binary_keyword_mode_is_not_a_hit(self):
        assert _names('handle = open(path, mode="wb")\n') == []

    def test_a_mode_that_is_not_a_literal_is_left_alone(self):
        """Whether it is text cannot be read from the statement; the checker declines."""
        assert _names("handle = open(path, mode)\n") == []


class TestWhatIsNeverConvicted:
    def test_an_encoding_keyword_acquits_the_call(self):
        assert _names('p.write_text(body, encoding="utf-8")\n') == []

    def test_a_positional_encoding_acquits_write_text(self):
        """write_text(data, encoding, ...) — the slot is the signature's own."""
        assert _names('p.write_text(body, "utf-8")\n') == []

    def test_a_positional_encoding_acquits_read_text(self):
        """read_text(encoding, ...) — encoding is the FIRST parameter here."""
        assert _names('p.read_text("utf-8")\n') == []

    def test_a_positional_encoding_acquits_open(self):
        assert _names('open(path, "w", -1, "utf-8")\n') == []

    def test_an_encoding_that_is_not_a_literal_acquits_the_call(self):
        """It is named. Which one it is, is the test's business."""
        assert _names("p.read_text(encoding=CHARSET)\n") == []

    def test_a_non_utf8_encoding_is_not_a_hit(self):
        """A test of latin-1 handling has to name latin-1."""
        assert _names('p.read_text(encoding="latin-1")\n') == []

    def test_read_bytes_and_write_bytes_are_not_hits(self):
        assert _names("a = p.read_bytes()\np.write_bytes(b'x')\n") == []

    def test_an_open_on_some_other_receiver_is_not_a_hit(self):
        """ZipFile.open is binary-only and gzip.open has its own mode vocabulary."""
        assert _names("handle = archive.open(name)\n") == []

    def test_a_kwargs_splat_acquits_the_call(self):
        """The splat can carry the encoding; nothing here can be read with confidence."""
        assert _names("p.write_text(body, **kwargs)\n") == []

    def test_an_args_splat_acquits_the_call(self):
        assert _names("open(*args)\n") == []


class TestTheNonUtf8CountIsRecordedNotCharged:
    def test_a_named_latin1_is_counted(self):
        assert named_encoding_check.named_other_encodings('p.read_text(encoding="latin-1")\n') == [(1, "latin-1")]

    def test_utf8_is_not_counted(self):
        assert named_encoding_check.named_other_encodings('p.read_text(encoding="utf-8")\n') == []

    def test_the_spelling_utf8_without_a_dash_is_not_counted(self):
        """Python accepts both spellings for the same codec."""
        assert named_encoding_check.named_other_encodings('p.read_text(encoding="UTF8")\n') == []

    def test_the_count_reaches_the_passing_message(self, tmp_path):
        path = _write(tmp_path, 'def test_x(p):\n    assert p.read_text(encoding="latin-1")\n')

        result = named_encoding_check.check_module(str(path))

        assert result["score"] == 100
        assert result["checks"][0]["message"] == (
            "Every text read and write names an encoding (1 call names latin-1, which the rule allows)"
        )


class TestTheFix:
    def test_the_fix_names_the_keyword_and_the_reason(self):
        fix = named_encoding_check.scan("p.write_text(body)\n")[0][2]

        assert 'encoding="utf-8"' in fix
        assert "cp1252" in fix


class TestCheckModuleIsThePerFileLane:
    def test_a_clean_file_scores_a_hundred(self, tmp_path):
        path = _write(tmp_path, 'def test_x(tmp_path):\n    (tmp_path / "a").write_text("b", encoding="utf-8")\n')

        result = named_encoding_check.check_module(str(path))

        assert result["passed"] is True
        assert result["score"] == 100

    def test_a_convicted_file_scores_zero(self, tmp_path):
        path = _write(tmp_path, 'def test_x(tmp_path):\n    (tmp_path / "a").write_text("b")\n')

        result = named_encoding_check.check_module(str(path))

        assert result["passed"] is False
        assert result["score"] == 0

    def test_every_hit_gets_its_own_line_with_file_and_number(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and counts the rest.

        So N checks would show one hit and hide the others; the lines live in
        one message instead, and this pins that they all survive.
        """
        path = _write(tmp_path, 'def test_x(p):\n    p.write_text("a")\n    assert p.read_text()\n')

        message = named_encoding_check.check_module(str(path))["checks"][0]["message"]

        assert message.splitlines() == [
            f"test_thing.py:2 write_text() without encoding - {named_encoding_check.FIX}",
            f"test_thing.py:3 read_text() without encoding - {named_encoding_check.FIX}",
        ]

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        result = named_encoding_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["passed"] is False
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_no_hits(self, tmp_path):
        """ruff already convicts the syntax error; guessing at line numbers would not help."""
        path = _write(tmp_path, "def test_x(:\n")

        assert named_encoding_check.check_module(str(path))["passed"] is True

    def test_a_file_bypass_acquits_the_whole_file(self, tmp_path):
        path = _write(tmp_path, 'p.write_text("a")\n')
        rules = [{"standard": "named_encoding", "file": str(path), "reason": "measured"}]

        result = named_encoding_check.check_module(str(path), bypass_rules=rules)

        assert result["passed"] is True
        assert "bypassed" in result["checks"][0]["message"]


class TestTheModelFileHoldsTheLine:
    """tests/test_readme_update.py is the fleet's gold test file for this item."""

    def test_the_model_file_passes(self):
        assert named_encoding_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_file_with_one_encoding_removed_is_convicted(self, tmp_path):
        """Not a hand-written sample: the real file, one keyword short."""
        source = MODEL.read_text(encoding="utf-8")
        mutated = source.replace('("# entry point\\n", encoding="utf-8")', '("# entry point\\n")', 1)
        assert mutated != source, "the anchor moved — repoint it at a real write_text"
        path = _write(tmp_path, mutated, name="test_readme_update.py")

        result = named_encoding_check.check_module(str(path))

        assert result["score"] == 0
        assert "write_text() without encoding" in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_an_unnamed_encoding(self, tmp_path, capsys):
        path = _write(tmp_path, 'def test_x(tmp_path):\n    (tmp_path / "a").write_text("b")\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — named_encoding" in out
        assert "cp1252" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, 'def test_x(tmp_path):\n    (tmp_path / "a").write_text("b", encoding="utf-8")\n')

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ named_encoding" in out
        assert "cp1252" not in out

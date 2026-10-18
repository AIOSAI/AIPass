# =================== AIPass ====================
# Name: test_posix_literal_nominator.py
# Description: pins for the POSIX-LITERAL nominator
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/tests_pytest_standards/posix_literal_check.py."""

# The premise is pinned first: ntpath reads a rooted literal as drive-relative, posixpath as
# absolute. If that stops being true this file goes red rather than nominating a defect nobody can hit.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — SPECIFICATION's rule, flags, exempts and evidence prose
# seedgo: no-test-needed(constant) — DIALECT_MODULES' membership, macpath included

import ast
import ntpath
import posixpath
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.tests_pytest_standards import adapter, corpus
from aipass.seedgo.apps.handlers.tests_pytest_standards import posix_literal_check as target


def _nominate(tmp_path: Path, source: str) -> list:
    """Run the nominator over one synthetic test module."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_subject.py").write_text(source, encoding="utf-8")
    ast.parse(source)  # a fixture that will not parse exercises the wrong arm
    scanned = corpus.build(tmp_path, ("tests",))
    return target.nominate(scanned)


class TestTheHazardItself:
    """The platform fact the whole rule rests on, measured not assumed."""

    def test_ntpath_does_not_call_a_rooted_literal_absolute(self):
        """The premise: ntpath.isabs is True for a rooted literal, yet it carries no drive for resolve() to keep."""
        assert ntpath.splitdrive("/tmp") == ("", "/tmp")
        assert posixpath.splitdrive("/tmp") == ("", "/tmp")
        # The half that differs: ntpath joins a drive onto it, posixpath cannot.
        assert ntpath.join("D:", "/tmp") == "D:/tmp"

    def test_a_rooted_literal_is_drive_relative_on_ntpath_only(self):
        """Same literal, two answers. This is the whole species in two lines."""
        assert ntpath.abspath("D:/x/../tmp") == "D:\\tmp"
        assert posixpath.abspath("/x/../tmp") == "/tmp"


class TestWhatItNominates:
    """The construct that took @drone's windows-setup leg down."""

    def test_a_path_literal_put_through_resolve_is_nominated(self, tmp_path):
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("/tmp").resolve() in roots\n',
        )
        assert len(rows) == 1, rows
        assert rows[0]["evidence"]["literal"] == "/tmp"

    def test_os_path_realpath_over_a_literal_is_nominated(self, tmp_path):
        rows = _nominate(
            tmp_path,
            'import os\n\n\ndef test_x():\n    assert os.path.realpath("/tmp") == "/tmp"\n',
        )
        assert len(rows) == 1, rows

    def test_a_windows_rooted_literal_is_nominated_too(self, tmp_path):
        r"""A hardcoded C:\ is the same claim the other way: the rule is portability, not a POSIX preference."""
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("C:\\\\tmp").resolve()\n',
        )
        assert len(rows) == 1, rows

    def test_the_nomination_names_the_literal_not_just_the_line(self, tmp_path):
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("/etc/passwd").resolve()\n',
        )
        assert "/etc/passwd" in rows[0]["why"]


class TestWhatItAcquits:
    """The acquittals are most of this rule - measured before it shipped."""

    def test_another_objects_resolve_verb_is_not_nominated(self, tmp_path):
        """A branch-name resolver sharing a verb with pathlib is not nominated: the rule keys on the receiver."""
        rows = _nominate(
            tmp_path,
            "def test_x():\n"
            '    resolved = registry.resolve("@canary", {"CANARY": Path("/x/canary")})\n'
            "    assert resolved\n",
        )
        assert rows == []

    def test_any_objects_resolve_handed_a_rooted_literal_directly_acquits(self, tmp_path):
        """A rooted literal handed straight to a foreign resolve is acquitted by the receiver test alone."""
        rows = _nominate(
            tmp_path,
            'def test_x():\n    assert branch_registry.resolve("/tmp")\n',
        )
        assert rows == []

    def test_a_realpath_on_a_non_path_module_acquits(self, tmp_path):
        """A realpath on a non-path module acquits: the os.path clause, which no other pin reaches."""
        rows = _nominate(
            tmp_path,
            'def test_x():\n    assert translator.realpath("/tmp")\n',
        )
        assert rows == []

    def test_a_relative_literal_is_not_nominated(self, tmp_path):
        """A relative fragment makes no platform claim to disagree about."""
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("tmp/x").resolve()\n',
        )
        assert rows == []

    def test_a_path_from_a_fixture_is_not_nominated(self, tmp_path):
        rows = _nominate(
            tmp_path,
            "def test_x(tmp_path):\n    assert tmp_path.resolve()\n",
        )
        assert rows == []

    def test_a_resolve_on_a_variable_is_not_nominated(self, tmp_path):
        """The stated limit: the rule reads the RECEIVER, so a literal that travelled through a name errs SHORT."""
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    p = Path("/tmp")\n    assert p.resolve()\n',
        )
        assert rows == []

    def test_an_empty_literal_is_not_nominated(self, tmp_path):
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("").resolve()\n',
        )
        assert rows == []


class TestTheNominatorShape:
    """The pack contract, so a broken group cannot ship green."""

    def test_it_declares_a_group_and_a_specification(self):
        assert target.GROUP == "static_posix_literal"
        assert target.SPECIFICATION["species"] == ["POSIX-LITERAL"]

    def test_it_is_registered_with_the_adapter(self):
        assert target.GROUP in adapter.STATIC_GROUPS

    def test_it_does_not_define_a_module_or_branch_check(self):
        """A nominator that grows a check_module becomes a convicting tier by accident (Law M1)."""
        assert not hasattr(target, "check_module")
        assert not hasattr(target, "check_branch")

    def test_the_spec_states_the_limit_the_live_run_actually_hit(self):
        """The limits list says a literal in a fixture is missed: the live run found 3 of 4 sites because of it."""
        limits = " ".join(target.SPECIFICATION["limits"])
        assert "fixture" in limits and "FEWER" in limits

    def test_the_fix_does_not_tell_anyone_to_delete_the_literal(self):
        """A rooted literal is drive-relative on Windows, not invalid; 'remove it' breaks tests whose subject IS it."""
        assert "keep it" in target.SPECIFICATION["fix"]

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("/tmp", True),
            ("\\\\server\\share", True),
            ("C:/tmp", True),
            ("c:\\tmp", True),
            ("tmp", False),
            ("", False),
            ("1:/tmp", False),
            ("./tmp", False),
        ],
    )
    def test_the_rooted_test_covers_both_dialects(self, tmp_path, text, expected):
        """A literal table, so this one cannot vanish. Mutant: a backslash root not rooted in apps/handlers/tests_pytest_standards/posix_literal_check.py — killed."""
        rows = _nominate(
            tmp_path, f"from pathlib import Path\n\n\ndef test_x():\n    assert Path({text!r}).resolve()\n"
        )
        assert (len(rows) == 1) is expected, rows

    def test_a_non_string_constant_is_not_rooted(self, tmp_path):
        """Mutant: the str guard dropped in apps/handlers/tests_pytest_standards/posix_literal_check.py — killed."""
        rows = _nominate(tmp_path, "from pathlib import Path\n\n\ndef test_x():\n    assert Path(47).resolve()\n")
        assert rows == []

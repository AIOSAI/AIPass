# =================== AIPass ====================
# Name: test_posix_literal_nominator.py
# Description: pins for the POSIX-LITERAL nominator
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

r"""Pins for the rooted-path-literal nominator.

THE FACT THIS RULE DEPENDS ON is pinned first, because @drone's round-7 note is
right: every rule has a premise underneath it and almost none of them say so out
loud. Here the premise is that ntpath treats a rooted literal as DRIVE-RELATIVE
while posixpath treats it as absolute. If that ever stops being true this file
goes red rather than quietly nominating a defect nobody can hit.
"""

import ast
import ntpath
import posixpath
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus
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
        """The premise. ntpath.isabs is True for a rooted literal, but the path
        carries no DRIVE, which is what makes resolve() attach the current one
        and hand back something the author never wrote."""
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

    def test_a_windows_rooted_literal_is_nominated_TOO(self, tmp_path):
        r"""The rule is not "POSIX spelling bad". A hardcoded C:\ is the same
        claim pointing the other way, and a rule that only caught one direction
        would be a platform preference wearing a portability name."""
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

    def test_another_objects_resolve_verb_is_NOT_nominated(self, tmp_path):
        """The measurement that decided the shape. Six of the ten sites a
        name-keyed rule found fleet-wide were this: a branch-name resolver
        sharing a verb with pathlib and holding a rooted literal in a dict value
        it never resolves. Keyed on the receiver, none of them are nominated."""
        rows = _nominate(
            tmp_path,
            "def test_x():\n"
            '    resolved = registry.resolve("@canary", {"CANARY": Path("/x/canary")})\n'
            "    assert resolved\n",
        )
        assert rows == []

    def test_any_objects_resolve_handed_a_rooted_literal_DIRECTLY_acquits(self, tmp_path):
        """The receiver test carrying its own weight, and it needed a second pin.

        The first acquittal above holds the literal inside a dict, so a mutant
        that dropped the receiver test and scanned the arguments instead SURVIVED
        it - the mutation was invisible to the only pin guarding the clause.
        This one hands the literal straight to a foreign resolve, where nothing
        but the receiver test can acquit it. Run round 7, M8.
        """
        rows = _nominate(
            tmp_path,
            'def test_x():\n    assert branch_registry.resolve("/tmp")\n',
        )
        assert rows == []

    def test_a_realpath_on_a_NON_PATH_module_acquits(self, tmp_path):
        """Guards the os.path clause, which no pin reached until a mutant
        deleting it survived the whole file. Run round 7, M11."""
        rows = _nominate(
            tmp_path,
            'def test_x():\n    assert translator.realpath("/tmp")\n',
        )
        assert rows == []

    def test_a_relative_literal_is_NOT_nominated(self, tmp_path):
        """A relative fragment makes no platform claim to disagree about."""
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    assert Path("tmp/x").resolve()\n',
        )
        assert rows == []

    def test_a_path_from_a_fixture_is_NOT_nominated(self, tmp_path):
        rows = _nominate(
            tmp_path,
            "def test_x(tmp_path):\n    assert tmp_path.resolve()\n",
        )
        assert rows == []

    def test_a_resolve_on_a_variable_is_NOT_nominated(self, tmp_path):
        """The stated limit, pinned so it is a decision rather than a surprise:
        this rule reads the RECEIVER, so a literal that travelled through a name
        is invisible to it. It errs SHORT."""
        rows = _nominate(
            tmp_path,
            'from pathlib import Path\n\n\ndef test_x():\n    p = Path("/tmp")\n    assert p.resolve()\n',
        )
        assert rows == []

    def test_an_empty_literal_is_NOT_nominated(self, tmp_path):
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
        from aipass.seedgo.apps.handlers.tests_pytest_standards import adapter

        assert target.GROUP in adapter.STATIC_GROUPS

    def test_it_does_not_define_a_module_or_branch_check(self):
        """A nominator that grows a check_module becomes a convicting tier by
        accident (Law M1)."""
        assert not hasattr(target, "check_module")
        assert not hasattr(target, "check_branch")

    def test_the_spec_states_the_limit_the_live_run_actually_hit(self):
        """Not decoration: running this over @drone's tree found 3 of the 4
        sites a whole-file scan finds, because the fourth sits in a fixture.
        The limits list has to say so."""
        limits = " ".join(target.SPECIFICATION["limits"])
        assert "fixture" in limits and "FEWER" in limits

    def test_the_fix_does_not_tell_anyone_to_delete_the_literal(self):
        """A rooted literal is drive-relative on Windows, not invalid. A fix
        line that says 'remove it' would break tests whose subject IS the
        literal."""
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
    def test_the_rooted_test_covers_both_dialects(self, text, expected):
        """A literal table, so this one cannot vanish."""
        assert target._is_rooted_literal(ast.Constant(value=text)) is expected

    def test_a_non_string_constant_is_not_rooted(self):
        assert target._is_rooted_literal(ast.Constant(value=47)) is False

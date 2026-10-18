# =================== META ====================
# Name: test_empty_parametrize_nominator.py
# Description: Pins the VANISHING-TABLE nominator against a table that can silently empty
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/tests_pytest_standards/empty_parametrize_check.py."""

# A parametrized test over an empty collection reports as passing.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the prose of nominate()'s message; species, line and argvalues are asserted

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus, empty_parametrize_check, nominators


def _nominate(source: str, tmp_path: Path):
    """Run the nominator over one synthetic test module."""
    target = tmp_path / "tests"
    target.mkdir(exist_ok=True)
    (target / "test_synthetic.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return empty_parametrize_check.nominate(corpus.build(tmp_path, ("tests",)))


class TestTheHazardItself:
    def test_the_hazard_is_real_on_this_pytest(self, tmp_path):
        """The file this pytest reports green is the file the rule nominates."""
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            @pytest.mark.parametrize("item", collect())
            def test_every_found_item_is_valid(item):
                assert item["ok"]
            """,
            tmp_path,
        )
        probe = tmp_path / "tests" / "test_synthetic.py"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-p", "no:randomly"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stdout
        assert "skipped" in result.stdout, result.stdout
        assert "failed" not in result.stdout, result.stdout
        assert [r["species"] for r in rows] == ["VANISHING-TABLE"], rows


class TestWhatItNominates:
    def test_a_table_drawn_from_a_call_is_nominated(self, tmp_path):
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert [r["species"] for r in rows] == ["VANISHING-TABLE"]
        assert "collect()" in rows[0]["evidence"]["argvalues"]

    def test_the_row_carries_the_decorator_line_not_the_functions(self, tmp_path):
        """The row carries the decorator's line, so the nomination sends its owner to the right place."""
        source = """
            import pytest

            def collect():
                return []

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """
        rows = _nominate(source, tmp_path)
        # Asserted against the FILE the nominator read: a hand-counted line is one dedent
        # away from testing the fixture instead of the rule.
        written = (tmp_path / "tests" / "test_synthetic.py").read_text(encoding="utf-8").split("\n")
        assert "parametrize" in written[rows[0]["line"] - 1], written[rows[0]["line"] - 1]


class TestWhatItAcquits:
    @pytest.mark.parametrize(
        "argvalues",
        ["[1, 2, 3]", "(1, 2)", '{"a", "b"}', "range(24)", "sorted(WORLDS)", "WORLDS"],
    )
    def test_a_table_that_cannot_be_empty_is_not_nominated(self, argvalues, tmp_path):
        """The acquittals matter more than the flags: a literal cannot vanish, nor a module constant bound to one."""
        rows = _nominate(
            f"""
            import pytest

            WORLDS = ["a", "b"]

            @pytest.mark.parametrize("item", {argvalues})
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert rows == [], rows

    def test_a_name_bound_to_something_unknown_is_still_nominated(self, tmp_path):
        """A module-level name bound to a call at import time is still a query, so it is still nominated."""
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            WORLDS = collect()

            @pytest.mark.parametrize("item", WORLDS)
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert len(rows) == 1, rows

    def test_an_empty_literal_is_still_nominated(self, tmp_path):
        """Negative control: `[]` written out is the defect in its most obvious form."""
        rows = _nominate(
            """
            import pytest

            @pytest.mark.parametrize("item", [])
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert len(rows) == 1

    def test_a_nonempty_only_guard_is_nominated_as_a_short_table(self, tmp_path):
        """A guard asserting only non-emptiness misses a collector that drops one entry: a short table."""
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            def test_the_collector_found_something():
                assert len(collect()) > 0

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert [r["species"] for r in rows] == ["SHORT-TABLE"], rows

    def test_a_guard_that_pins_an_expected_count_is_acquitted(self, tmp_path):
        """The full acquittal: the expected count derived from the RAW DATA, not from the collector under judgement."""
        rows = _nominate(
            """
            import json
            import pytest

            def collect():
                return []

            def test_the_collector_found_them_all():
                raw = json.loads(RAW.read_text())["bypass"]
                expected = sum(1 for rule in raw if rule.get("lines"))
                assert len(collect()) == expected

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert rows == []

    def test_len_compared_against_zero_is_not_a_count_guard(self, tmp_path):
        """`len(x) == 0` is an emptiness assertion wearing a count's shape, so it acquits nothing."""
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            def test_nothing_left_over():
                assert len(collect()) == 0

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert [r["species"] for r in rows] == ["SHORT-TABLE"], rows

    def test_a_safe_builtin_over_a_call_is_still_nominated(self, tmp_path):
        """The unwrap goes one layer and judges what it finds: sorted() of a query is still a query."""
        rows = _nominate(
            """
            import pytest

            def collect():
                return []

            @pytest.mark.parametrize("item", sorted(collect()))
            def test_each(item):
                assert item
            """,
            tmp_path,
        )
        assert len(rows) == 1


class TestTheNominatorShape:
    def test_it_satisfies_the_pack_contract(self):
        """Law S7a and the shape gate: a nominator exposing check_module would be scored as a standard."""
        assert nominators.shape_problems(empty_parametrize_check) == []

    def test_the_pack_discovers_it(self):
        modules, errors = nominators.discover()
        assert errors == []
        assert "static_empty_parametrize" in modules

    def test_the_specification_names_the_cure_not_just_the_defect(self):
        """The fix says why the obvious probe does not work, not just 'do not do that'."""
        fix = empty_parametrize_check.SPECIFICATION["fix"]
        assert "raw data" in fix
        assert "cannot detect a blinded collector" in fix

    def test_the_module_parses_and_declares_its_limits(self):
        """Law S8: a score without a declared blind spot is a refusal."""
        assert empty_parametrize_check.SPECIFICATION["limits"]
        source = Path(empty_parametrize_check.__file__).read_text(encoding="utf-8")
        ast.parse(source)

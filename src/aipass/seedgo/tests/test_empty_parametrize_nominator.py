# =================== META ====================
# Name: test_empty_parametrize_nominator.py
# Description: Pins the VANISHING-TABLE nominator against a table that can silently empty
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""A parametrized test over an empty collection reports as passing.

@drone found it building the content-anchored bypass rule (2026-08-31): their
first ``test_bypass_anchors.py`` SURVIVED a mutant that blinded the collector to
``return []``, because the anchor checks were parametrized over the collector's
output and pytest reports a parametrized test with no cases as SKIPPED. The file
printed "1 passed, 2 skipped" and exit code 0 for an instrument that had checked
nothing.

Reproduced independently here before the rule was written — see
``test_the_hazard_is_real_on_this_pytest`` — because a rule built on a reported
behaviour that this pytest does not actually have would nominate a defect nobody
can hit.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus, empty_parametrize_check


def _nominate(source: str, tmp_path: Path):
    """Run the nominator over one synthetic test module."""
    target = tmp_path / "tests"
    target.mkdir(exist_ok=True)
    (target / "test_synthetic.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return empty_parametrize_check.nominate(corpus.build(tmp_path, ("tests",)))


class TestTheHazardItself:
    def test_the_hazard_is_real_on_this_pytest(self, tmp_path):
        """The measurement the rule stands on, not a citation of it.

        A parametrized test over an empty collection must report SKIPPED with
        an exit code of 0 — green — on the pytest actually installed here. If a
        future pytest made this an error the rule would be nominating a defect
        that can no longer happen, and this goes red rather than the rule
        quietly outliving its reason.
        """
        probe = tmp_path / "test_probe.py"
        probe.write_text(
            textwrap.dedent(
                """
                import pytest

                def collect():
                    return []

                @pytest.mark.parametrize("item", collect())
                def test_every_found_item_is_valid(item):
                    assert item["ok"]
                """
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(probe), "-q", "-p", "no:randomly"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stdout
        assert "skipped" in result.stdout, result.stdout
        assert "failed" not in result.stdout, result.stdout


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
        """A nomination that points at the wrong line sends its owner to the
        wrong place, which is the whole complaint behind @memory's line-40-for-
        line-106 finding."""
        source = """
            import pytest

            def collect():
                return []

            @pytest.mark.parametrize("item", collect())
            def test_each(item):
                assert item
            """
        rows = _nominate(source, tmp_path)
        # Asserted against the FILE the nominator read, not against a number
        # counted by hand — a hardcoded line is one dedent away from testing the
        # fixture instead of the rule.
        written = (tmp_path / "tests" / "test_synthetic.py").read_text(encoding="utf-8").split("\n")
        assert "parametrize" in written[rows[0]["line"] - 1], written[rows[0]["line"] - 1]


class TestWhatItAcquits:
    @pytest.mark.parametrize(
        "argvalues",
        ["[1, 2, 3]", "(1, 2)", '{"a", "b"}', "range(24)", "sorted(WORLDS)", "WORLDS"],
    )
    def test_a_table_that_cannot_be_empty_is_not_nominated(self, argvalues, tmp_path):
        """The acquittals matter more than the flags. A literal cannot vanish,
        and neither can a module constant bound to one."""
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

    def test_a_name_bound_to_something_UNKNOWN_is_still_nominated(self, tmp_path):
        """Mutation control (M18, survived the first run). Acquitting every
        module-level name would wave through a table built by a call at import
        time — the same query, one line higher up."""
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

    def test_an_EMPTY_literal_is_still_nominated(self, tmp_path):
        """Negative control for the acquittal above: `[]` written out is the
        defect in its most obvious form, and a rule that acquitted every
        literal would wave it through."""
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

    def test_a_nonempty_only_guard_is_nominated_as_a_SHORT_TABLE(self, tmp_path):
        """THE RULING CHANGED IN ROUND 9 and this pin records the change.

        It used to assert a full acquittal: a file asserting its collection is
        non-empty had done the thing this rule asks for. @trigger found the
        hole by applying my own sentence to their own pins - a guard asserting
        non-emptiness catches a collector blinded ENTIRELY and misses one that
        drops a single entry. The table stays non-empty, every surviving case
        passes, and the run is quietly short.

        Measured before the split: 10 files fleet-wide are acquitted by the
        guard clause, 7 already pin a count, 3 do not. Three sites, not a tree.
        """
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

    def test_a_guard_that_pins_an_expected_COUNT_is_acquitted(self, tmp_path):
        """The full acquittal, and the shape @trigger shipped: the expected
        number derived from the RAW DATA rather than from the collector under
        judgement, so a dropped entry has something to fail against."""
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

    def test_len_compared_against_ZERO_is_not_a_count_guard(self, tmp_path):
        """`len(x) == 0` is an emptiness assertion wearing a count's shape, and
        acquitting on it would hand a full pass to the one comparison that
        proves the table IS empty."""
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

    def test_a_safe_builtin_over_a_CALL_is_still_nominated(self, tmp_path):
        """The unwrap goes one layer and judges what it finds. sorted() of a
        query is still a query."""
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
        """Law S7a and the shape gate: a nominator that exposed check_module
        would be scored by the file-walk engine as if it were a standard."""
        from aipass.seedgo.apps.handlers.tests_pytest_standards import nominators

        assert nominators.shape_problems(empty_parametrize_check) == []

    def test_the_pack_discovers_it(self):
        from aipass.seedgo.apps.handlers.tests_pytest_standards import nominators

        modules, errors = nominators.discover()
        assert errors == []
        assert "static_empty_parametrize" in modules

    def test_the_specification_names_the_cure_not_just_the_defect(self):
        """A nomination whose fix is 'do not do that' teaches nothing. The
        cure has to say why the obvious probe does not work."""
        fix = empty_parametrize_check.SPECIFICATION["fix"]
        assert "raw data" in fix
        assert "cannot detect a blinded collector" in fix

    def test_the_module_parses_and_declares_its_limits(self):
        """Law S8: a score without a declared blind spot is a refusal."""
        assert empty_parametrize_check.SPECIFICATION["limits"]
        source = Path(empty_parametrize_check.__file__).read_text(encoding="utf-8")
        ast.parse(source)

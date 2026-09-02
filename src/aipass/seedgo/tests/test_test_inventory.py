# =================== AIPass ====================
# Name: test_test_inventory.py
# Description: behavioural pins for the test-inventory verb
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Pins for the ranked test inventory. Every test here names a DEFECT.

Patrick's standing rule governs this file: never add a test without a defect it
pins. The tool is a report about test bloat, so a pile of instruments defending
it would be the joke telling itself. What is pinned is what a future change
could plausibly break, and several of these reproduce a defect that was real
during the build:

  * the closed mock-assert set (a prefix rule read a project helper named
    `assert_row_shape` as a mock assertion and filed a checking test as a
    change detector)
  * `importorskip` as CONDITIONAL rather than skipped (a measured miss: this
    fleet's bluesky driver importorskips a package that IS installed, and
    calling it skipped under-counted 12 running tests)
  * the conftest ignore scope (a basename match would silence every `parked/`
    in the fleet from one branch's file)
  * the blame range starting at the first DECORATOR (a `@parametrize` table
    attributed to whichever function sits above it)
  * a process-salted body fingerprint (two runs over an unchanged tree
    publishing different values, making every diff of the artifact noise)

NOTHING HERE ASSERTS A FACT ABOUT THIS MACHINE. No test claims a fleet count, a
Python version, or a platform. That species cost this campaign twelve hours and
thirteen CI rounds, and it is exactly what the tool under test exists to find.
"""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.test_inventory import collection, exclusions, history, ranking, report, shape


def _function(source: str) -> ast.AST:
    """The first function node in a source snippet."""
    return ast.parse(textwrap.dedent(source)).body[0]


def _classify(source: str) -> shape.Shape:
    """The assertion shape of one written-out test function."""
    return shape.classify(_function(source))


# =============================================================================
# ASSERTION SHAPE
# =============================================================================


class TestAssertionShape:
    """What the NONE / MOCK_ONLY / REAL column convicts, and what it clears."""

    def test_a_function_that_checks_nothing_is_convicted_as_shapeless(self):
        """The planted case. A smoke test that only proves no exception raised.

        This is the shape the whole report exists to surface, and the one live
        example that opened the queue on the first fleet run was seedgo's own:
        `print_branch_summary(result)` on a line by itself.
        """
        found = _classify(
            """
            def test_basic_summary():
                result = _make_audit_result()
                print_branch_summary(result)
            """
        )

        assert found.shape == shape.SHAPE_NONE
        assert found.delegated_oracle is False

    def test_a_test_that_only_checks_its_own_doubles_is_mock_only_not_real(self):
        """A change detector must not be cleared as a checking test.

        arXiv:2606.18168 names this W4 across 86,156 agent-authored patches.
        Folding it into REAL would hide the second-largest species in the
        report behind the largest.
        """
        found = _classify(
            """
            def test_writes_the_row(mock_store):
                write_row(mock_store, {"a": 1})
                mock_store.save.assert_called_once_with({"a": 1})
            """
        )

        assert found.shape == shape.SHAPE_MOCK_ONLY

    def test_a_project_helper_named_assert_something_is_not_read_as_a_mock(self):
        """THE DEFECT: `startswith("assert_")` reads a project helper as a mock.

        `assert_row_shape(...)` is a delegated oracle - a real check one call
        away - and a prefix rule files the test that calls it under MOCK_ONLY,
        beside the change detectors it has nothing to do with. The mock set is
        closed for this reason.
        """
        found = _classify(
            """
            def test_the_row_is_shaped_right():
                assert_row_shape(build_row())
            """
        )

        assert found.shape != shape.SHAPE_MOCK_ONLY
        assert found.delegated_oracle is True

    def test_pytest_raises_as_a_context_manager_is_a_real_oracle(self):
        """A test with no `assert` statement can still check something.

        `with pytest.raises(...)` is the common spelling and it appears in no
        `ast.Assert` node. Missing it would convict a large, correct family of
        exception tests as assertion-free.
        """
        found = _classify(
            """
            def test_refuses_a_bad_path():
                with pytest.raises(ValueError):
                    resolve("nope")
            """
        )

        assert found.shape == shape.SHAPE_REAL

    def test_the_body_fingerprint_survives_a_new_process(self):
        """THE DEFECT: `hash()` is salted per process (PEP 456).

        A salted fingerprint means two runs over an unchanged tree publish
        different values for every row, so every diff of the artifact is noise
        and the twins column silently regroups between runs.
        """
        snippet = "def test_x():\n    value = 1\n    assert value"
        script = (
            "import ast, sys;"
            "sys.path.insert(0, %r);"
            "from aipass.seedgo.apps.handlers.test_inventory import shape;"
            "print(shape.fingerprint(ast.parse(%r).body[0]))" % (_src_root(), snippet)
        )

        first = _in_fresh_process(script)
        second = _in_fresh_process(script)

        assert first == second
        assert first == shape.fingerprint(_function(snippet))


def _src_root() -> str:
    """The importable source root, so a child process can find the package."""
    return str(Path(collection.__file__).resolve().parents[5])


def _in_fresh_process(script: str) -> str:
    """Run a snippet in a new interpreter, with a new hash seed."""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"PYTHONHASHSEED": "random", "PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


# =============================================================================
# THE CORPUS DEFINITION
# =============================================================================


class TestWhatCountsAsATest:
    """The collection rules, which decide every number in the report."""

    def test_a_helper_class_contributes_no_tests(self, tmp_path):
        """pytest collects methods from `Test*` classes and no others.

        The audit-tests lane's corpus deliberately takes methods from ANY
        class, because static nomination should be generous. An inventory that
        inherited that generosity would report tests that cannot run.
        """
        _write(
            tmp_path,
            "tests/test_a.py",
            """
            class Helper:
                def test_not_really(self):
                    assert True

            class TestReal:
                def test_really(self):
                    assert True
            """,
        )

        names = {func.name for func in collection.collect(tmp_path).functions}

        assert names == {"test_really"}

    def test_a_test_class_with_a_constructor_collects_nothing(self, tmp_path):
        """pytest skips a `Test*` class that defines `__init__`, with a warning.

        Counting its methods would put tests in the inventory that never run,
        under a heading that says they do.
        """
        _write(
            tmp_path,
            "tests/test_b.py",
            """
            class TestWithInit:
                def __init__(self):
                    self.x = 1

                def test_never_runs(self):
                    assert True
            """,
        )

        assert collection.collect(tmp_path).functions == []

    def test_a_dot_directory_is_pruned(self, tmp_path):
        """`norecursedirs` carries `.*`, which is what keeps `.archive` out.

        Losing it silently adds every parked and archived file to the corpus,
        inflating the totals with code nobody runs and nobody maintains.
        """
        _write(tmp_path, "tests/.archive/test_old.py", "def test_old():\n    assert True")
        _write(tmp_path, "tests/test_live.py", "def test_live():\n    assert True")

        names = {func.name for func in collection.collect(tmp_path).functions}

        assert names == {"test_live"}

    def test_the_blame_range_starts_at_the_first_decorator(self, tmp_path):
        """A `@parametrize` table is part of the test that carries it.

        Starting the range at `def` attributes the decorator lines to whatever
        function sits above, so one test's churn lands on its neighbour's row -
        and a parametrised test looks older than the table it was given.
        """
        _write(
            tmp_path,
            "tests/test_c.py",
            """
            @pytest.mark.parametrize("value", [1, 2])
            def test_values(value):
                assert value
            """,
        )

        func = collection.collect(tmp_path).functions[0]

        assert func.blame_from < func.lineno


def _write(root: Path, relpath: str, source: str) -> Path:
    """One file, dedented, with its parents made."""
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


# =============================================================================
# TESTS THAT EXIST AND NEVER RUN
# =============================================================================


class TestExclusions:
    """Files pytest refuses to run, and the two mechanisms that do it."""

    def test_a_conftest_ignore_glob_silences_only_its_own_directory(self, tmp_path):
        """THE DEFECT: a basename match silences every `parked/` in the fleet.

        pytest resolves each pattern against the CONFTEST'S directory. A
        `parked/conftest.py` saying `["*"]` must silence its own directory and
        no other, or one branch's parked tests delete another branch's live
        ones from the report.
        """
        _write(tmp_path, "tests/parked/conftest.py", 'collect_ignore_glob = ["*"]')
        _write(tmp_path, "tests/parked/test_parked.py", "def test_parked():\n    assert True")
        _write(tmp_path, "tests/other/test_live.py", "def test_live():\n    assert True")

        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)

        assert statuses["tests/parked/test_parked.py"] == exclusions.STATUS_CONFTEST_IGNORE
        assert statuses["tests/other/test_live.py"] == exclusions.STATUS_COLLECTED

    def test_importorskip_is_conditional_and_a_bare_skip_is_not(self, tmp_path):
        """THE MEASURED MISS. Whether an `importorskip` file runs is a HOST fact.

        This fleet's bluesky driver importorskips a package that IS installed
        here, so folding it into MODULE_LEVEL_SKIP under-counted twelve running
        tests on the very machine doing the counting. An unconditional `skip`
        is a different thing and keeps its own status.
        """
        _write(
            tmp_path,
            "tests/test_parked.py",
            """
            import pytest as _parked

            _parked.skip("parked by ruling", allow_module_level=True)

            def test_never():
                assert True
            """,
        )
        _write(
            tmp_path,
            "tests/test_optional.py",
            """
            import pytest

            pytest.importorskip("some_optional_package")

            def test_maybe():
                assert True
            """,
        )

        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)

        assert statuses["tests/test_parked.py"] == exclusions.STATUS_MODULE_SKIP
        assert statuses["tests/test_optional.py"] == exclusions.STATUS_CONDITIONAL_SKIP
        assert exclusions.STATUS_CONDITIONAL_SKIP in exclusions.RUNNING_STATUSES
        assert exclusions.STATUS_MODULE_SKIP not in exclusions.RUNNING_STATUSES

    def test_a_pytest_alias_still_reads_as_pytest(self, tmp_path):
        """THE DEFECT: matching the literal word `pytest` misses an alias.

        The file that produced this rule writes `import pytest as _parked`, and
        a name-matched check reads a deliberately parked module as live.
        """
        _write(
            tmp_path,
            "tests/test_aliased.py",
            """
            import pytest as _elsewhere

            _elsewhere.skip("parked", allow_module_level=True)

            def test_never():
                assert True
            """,
        )

        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)

        assert statuses["tests/test_aliased.py"] == exclusions.STATUS_MODULE_SKIP


# =============================================================================
# AGE AND AUTHORSHIP
# =============================================================================


PORCELAIN = """\
1111111111111111111111111111111111111111 1 1 2
author Alice
author-time 1000000
author-tz +0000
summary first
filename f.py
\tline one
1111111111111111111111111111111111111111 2 2
\tline two
2222222222222222222222222222222222222222 3 3 1
author Bob
author-time 2000000
author-tz +0000
summary second
filename f.py
\tline three
"""


class TestHistory:
    """What blame is read as saying, and what it is not."""

    def test_a_repeated_commit_keeps_its_author(self):
        """THE DEFECT: porcelain emits the full header ONCE per commit.

        Every later hunk from the same commit carries only the sha line. A
        parser expecting a header per line attributes those lines to nobody,
        which reads as an untracked file with an author.
        """
        parsed = history.parse_porcelain(PORCELAIN)

        assert parsed.authors == {1: "Alice", 2: "Alice", 3: "Bob"}
        assert parsed.times[3] == 2000000

    def test_the_author_is_whoever_owns_the_most_lines(self):
        """A one-line fix by a second hand does not re-author the test.

        Taking the LAST toucher would re-attribute a whole generated batch to
        whoever most recently ran a formatter over the file.
        """
        parsed = history.parse_porcelain(PORCELAIN)

        attributed = history.attribute(parsed, 1, 3, now=3000000.0)

        assert attributed.author == "Alice"

    def test_each_function_is_attributed_over_its_own_lines(self):
        """Two adjacent functions must not inherit each other's history."""
        parsed = history.parse_porcelain(PORCELAIN)

        first = history.attribute(parsed, 1, 2, now=3000000.0)
        second = history.attribute(parsed, 3, 3, now=3000000.0)

        assert (first.author, second.author) == ("Alice", "Bob")
        first_age, second_age = first.age_days, second.age_days
        assert first_age is not None
        assert second_age is not None
        assert first_age > second_age

    def test_a_file_with_no_history_says_untracked_rather_than_defaulting(self):
        """A test with no history is a different object from an ordinary one.

        Defaulting it to an author, or to age zero, hides the finding: three
        test files on this fleet have no history at all and two of them run in
        CI.
        """
        attributed = history.attribute(history.LineHistory(authors={}, times={}, tracked=False), 1, 10, now=3000000.0)

        assert attributed.author_bucket == history.BUCKET_UNTRACKED
        assert attributed.age_days is None

    def test_an_unrecognised_author_goes_to_other_and_never_to_human(self):
        """THE DEFECT: defaulting unknown names into the smallest bucket.

        On this fleet the `human` bucket holds about fifty tests out of twenty
        thousand, so one unrecognised agent identity would multiply the most
        decision-relevant number in the report.
        """
        assert history.bucket_for("SomeNewAgent") == history.BUCKET_OTHER
        assert history.bucket_for("AIOSAI") == "AGENT_AIOSAI"


# =============================================================================
# THE SCORE, AND WHAT IT REFUSES TO SAY
# =============================================================================


class TestScoring:
    """The composite, and the vocabulary gate around the artifact."""

    def test_every_component_is_visible_and_they_sum_to_the_composite(self):
        """A reader who disagrees with the weighting must be able to re-sort.

        A composite published without its parts cannot be argued with, and the
        weighting is a judgement rather than a measurement. If the arithmetic
        and the published components ever diverge, the row is a claim nobody
        can check.
        """
        scored = ranking.score(
            _classify("def test_x():\n    call_it()"),
            history.FunctionHistory(
                author="AIOSAI", author_bucket="AGENT_AIOSAI", age_days=10.0, days_since_touch=5.0, lines=4
            ),
            twins=4,
            file_tests=50,
        )

        assert set(scored.components) == set(ranking.WEIGHTS)
        assert scored.review_priority == pytest.approx(
            sum(part["weighted"] for part in scored.components.values()), abs=1e-4
        )
        assert sum(ranking.WEIGHTS.values()) == pytest.approx(1.0)

    def test_an_unknown_age_contributes_nothing_rather_than_reading_as_young(self):
        """THE DEFECT: `None` treated as zero days puts untracked files on top.

        They already earn full authorship weight for having no recorded reason
        to exist. Scoring an absent age as brand new would double-count the
        same fact and push a real finding down the queue behind it.
        """
        untracked = history.FunctionHistory(
            author="", author_bucket=history.BUCKET_UNTRACKED, age_days=None, days_since_touch=None, lines=0
        )

        scored = ranking.score(_classify("def test_x():\n    assert True"), untracked, twins=1, file_tests=1)

        assert scored.components["recency"]["value"] == 0.0

    def test_publishing_without_blind_spots_is_refused(self):
        """The blind spots are the load-bearing half of an honest report.

        A reader who opens the rows and not the documentation is the normal
        reader. A version of this artifact that lost the list would look more
        authoritative than the one that has it.
        """
        with pytest.raises(ValueError, match="blind spots"):
            report.assert_publishable({"blind_spots": []})

    def test_a_delete_family_word_in_a_published_label_refuses_the_write(self):
        """THE WHOLE ARGUMENT, defended in code rather than in prose.

        ISSTA 2018 is why no static signal here may authorise a removal. A
        later contributor adding a band called `dead` would concede that
        argument silently, so the write refuses instead of warning.
        """
        summary = {
            "blind_spots": ["something"],
            "ranking": {"means": "mentions delete, deliberately, in prose"},
            "bands": {"keep": 1, "dead": 2},
        }

        with pytest.raises(ValueError, match="delete-family"):
            report.assert_publishable(summary)

    def test_prose_may_say_the_word_a_label_may_not(self):
        """The negative control, pinning CATEGORY_LENGTH from BOTH sides.

        A first version of this control passed the real blind-spot list and
        asserted no refusal - and a mutation sweep raised CATEGORY_LENGTH to
        ten thousand without failing it, because none of that prose happens to
        contain a literal delete-family word. The control was a control over
        nothing. So the two arms are CONSTRUCTED here: the same word, once in a
        sentence long enough to be an explanation and once short enough to be a
        category, must get two different answers.
        """
        explanation = (
            "This report will never tell anyone to delete a test, because no static signal "
            "measured here predicts what a removal would cost."
        )
        assert len(explanation) > report.CATEGORY_LENGTH
        assert ranking.delete_language_in(explanation)

        report.assert_publishable({"blind_spots": ["something"], "note": explanation})

        with pytest.raises(ValueError, match="delete-family"):
            report.assert_publishable({"blind_spots": ["something"], "note": "delete"})

    def test_the_real_published_prose_is_publishable(self):
        """The shipped strings pass their own gate.

        Pinned separately from the boundary above because these two can fail
        independently: a future blind spot written just under the category
        length, using the word, would refuse every run of the tool and the
        boundary test would still be green.
        """
        report.assert_publishable(
            {
                "blind_spots": list(report.BLIND_SPOTS),
                "ranking": {"means": ranking.NEVER_A_DELETE_VERDICT},
                "assertion_shape": {"counts": {"NONE": 1}},
            }
        )


# =============================================================================
# END TO END
# =============================================================================


class TestPublication:
    """One small tree, all the way through to files on disk."""

    def test_a_built_tree_publishes_rows_a_summary_and_a_digest(self, tmp_path):
        """The pipeline holds together and writes where it is told.

        Pinned because `publish` defaults to seedgo's own `.seedgo/`: a caller
        that could not redirect it would make every test of this module write
        into the branch's real artifact directory.
        """
        _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True")
        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)
        blames = {relpath: history.LineHistory({}, {}, tracked=False) for relpath in found.files}

        inventory = report.build(tmp_path, found, statuses, blames, now=1_000_000.0)
        paths = report.publish(inventory, directory=tmp_path / "out")

        rows = [json.loads(line) for line in paths["rows"].read_text().splitlines()]
        summary = json.loads(paths["summary"].read_text())

        assert [row["nodeid"] for row in rows] == ["tests/test_x.py::test_x"]
        assert summary["blind_spots"]
        assert summary["ranking"]["authorises_deletion"] is False
        assert paths["readable"].read_text().startswith("# Test inventory")

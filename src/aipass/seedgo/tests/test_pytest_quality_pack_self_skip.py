# =================== AIPass ====================
# Name: test_pytest_quality_pack_self_skip.py
# Description: pytest_quality pack, self_skip checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/self_skip_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/self_skip_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, self_skip_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


def _skip_rows(root: Path) -> list:
    """Every skip-provenance finding in a written-out project."""
    return self_skip_check.find_self_skips(corpus.build(root, test_dirs=self_skip_check.TEST_DIRS))


def _skip_species(root: Path) -> list:
    """The findings as `(species, nodeid)` pairs, for a compact assertion."""
    return [(row["species"], row["nodeid"]) for row in _skip_rows(root)]


def _self_skip_project(root: Path) -> Path:
    """A four-unit file where exactly one unit skips on the subject."""
    _write(
        root,
        "tests/test_skips.py",
        """
        import os
        import sys

        import pytest

        from mypkg import registry


        @pytest.mark.skipif(sys.platform == "win32", reason="posix only")
        def test_gates_on_the_platform():
            assert registry.build() is not None


        @pytest.mark.skipif(os.environ.get("CI") is None, reason="ci only")
        def test_gates_on_the_environment():
            assert registry.build() is not None


        @pytest.mark.skipif(not hasattr(registry, "build"), reason="not available")
        def test_gates_on_the_subject():
            assert registry.build() is not None


        def test_does_not_gate_at_all():
            assert registry.build() is not None
        """,
    )
    return root


class TestSelfSkipProvenance:
    """Machine, subject, or nothing - the three answers and only one defect."""

    def test_a_skipif_asking_hasattr_is_flagged_as_skip_on_drift(self, tmp_path):
        """The defining shape: rename the symbol and the test vanishes, not fails."""
        rows = _skip_rows(_self_skip_project(tmp_path))

        assert [(row["species"], row["nodeid"]) for row in rows] == [
            ("SKIP-ON-DRIFT", "tests/test_skips.py::test_gates_on_the_subject")
        ]
        assert "renaming that symbol makes this test vanish instead of fail" in rows[0]["reason"]

    def test_a_machine_probe_acquits_the_whole_site(self, tmp_path):
        """NEGATIVE CONTROL: a platform gate is correct code and must never flag."""
        assert [row["nodeid"] for row in _skip_rows(_self_skip_project(tmp_path))] == [
            "tests/test_skips.py::test_gates_on_the_subject"
        ]

    def test_a_machine_probe_acquits_even_when_a_hasattr_sits_beside_it(self, tmp_path):
        """THE ORDERING PIN: the acquittal has to be decided before the probe."""
        _write(
            tmp_path,
            "tests/test_mixed.py",
            """
            import sys

            import pytest

            from mypkg import registry


            @pytest.mark.skipif(
                sys.platform == "win32" or not hasattr(registry, "build"), reason="posix and built"
            )
            def test_gates_on_both():
                assert registry.build() is not None
            """,
        )

        assert _skip_rows(tmp_path) == []

    def test_an_unconditional_skip_decorator_is_perma_skip(self, tmp_path):
        """A test that never runs proves nothing, whatever it asserts."""
        _write(
            tmp_path,
            "tests/test_perma.py",
            """
            import pytest


            @pytest.mark.skip(reason="flaky, will fix")
            def test_the_important_thing():
                assert everything_works()
            """,
        )

        assert _skip_species(tmp_path) == [("PERMA-SKIP", "tests/test_perma.py::test_the_important_thing")]

    def test_a_condition_reading_a_name_imported_from_the_subject_is_self_skip(self, tmp_path):
        """The same defect one step less obvious than `hasattr`."""
        _write(
            tmp_path,
            "tests/test_reads.py",
            """
            import pytest

            from mypkg.storage import JSON_DIR


            def test_writes_the_row():
                if JSON_DIR is None:
                    pytest.skip("no dir")
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SELF-SKIP"]
        assert "reads 'JSON_DIR' from the subject under test" in rows[0]["reason"]

    def test_a_body_skip_is_classified_by_the_if_that_guards_it(self, tmp_path):
        """A guarded `pytest.skip()` is conditional, not unconditional."""
        _write(
            tmp_path,
            "tests/test_guarded.py",
            """
            import shutil

            import pytest


            def test_reads_the_log():
                if shutil.which("git") is None:
                    pytest.skip("git not installed")
                assert True
            """,
        )

        assert _skip_rows(tmp_path) == []

    def test_a_bare_body_skip_with_no_guard_is_perma_skip(self, tmp_path):
        """The other side of the same contract: no guard really is unconditional."""
        _write(
            tmp_path,
            "tests/test_bare.py",
            """
            import pytest


            def test_not_written_yet():
                pytest.skip("todo")
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("PERMA-SKIP", "tests/test_bare.py::test_not_written_yet")]


class TestSelfSkipOneHop:
    """The provenance is often one function or one module-level name away."""

    def test_a_condition_calling_a_local_helper_is_followed_one_hop(self, tmp_path):
        """`if not _factory_still_there():` hides the probe one call away."""
        _write(
            tmp_path,
            "tests/test_hop.py",
            """
            import pytest

            from mypkg import factory


            def _factory_still_raises():
                return hasattr(factory, "raise_on_unknown")


            @pytest.mark.skipif(not _factory_still_raises(), reason="behaviour changed")
            def test_rejects_unknown():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SKIP-ON-DRIFT"]
        assert "through the local helper _factory_still_raises()" in rows[0]["reason"]

    def test_a_module_level_flag_is_followed_to_the_statement_that_computes_it(self, tmp_path):
        """THE STATEMENT, NOT THE ASSIGNMENT - the reasoning is in the loop."""
        _write(
            tmp_path,
            "tests/test_flag.py",
            """
            import pytest

            import mypkg

            _HAS_IT = False
            for _candidate in ("build", "make"):
                if hasattr(mypkg, _candidate):
                    _HAS_IT = True


            @pytest.mark.skipif(not _HAS_IT, reason="entry point renamed")
            def test_builds():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SKIP-ON-DRIFT"]
        assert "through the module-level name _HAS_IT" in rows[0]["reason"]

    def test_the_reported_provenance_names_the_source_that_carried_the_answer(self, tmp_path):
        """A finding proved by a binding must not be blamed on an unrelated helper."""
        _write(
            tmp_path,
            "tests/test_blame.py",
            """
            import pytest

            import mypkg

            _HAS_IT = False
            for _candidate in ("build",):
                if hasattr(mypkg, _candidate):
                    _HAS_IT = True


            def _threshold():
                return 3


            @pytest.mark.skipif(_threshold() > 2 and not _HAS_IT, reason="entry point renamed")
            def test_builds():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert len(rows) == 1
        assert "through the module-level name _HAS_IT" in rows[0]["reason"]
        assert "_threshold" not in rows[0]["reason"]


class TestSelfSkipModuleScope:
    """The file-wide skip: the most expensive one, and it belongs to no function."""

    def test_a_module_level_skip_is_reported_against_the_file(self, tmp_path):
        """This is the shape that took 75 tests and it belongs to no test function."""
        _write(
            tmp_path,
            "tests/test_module_gate.py",
            """
            import pytest

            import mypkg.storage as storage

            if not hasattr(storage, "JSON_DIR"):
                pytest.skip("storage layout changed", allow_module_level=True)


            def test_writes_the_row():
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("SKIP-ON-DRIFT", "tests/test_module_gate.py::<module>")]

    def test_a_skip_inside_a_function_is_not_also_charged_to_the_module(self, tmp_path):
        """NEGATIVE CONTROL: one skip is one finding, in one scope."""
        _write(
            tmp_path,
            "tests/test_body_only.py",
            """
            import pytest

            from mypkg.storage import JSON_DIR


            def test_writes_the_row():
                if JSON_DIR is None:
                    pytest.skip("no dir")
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("SELF-SKIP", "tests/test_body_only.py::test_writes_the_row")]


class TestSelfSkipScoring:
    """The denominator, the dedupe, and the number that comes out."""

    def test_the_denominator_counts_file_scopes_so_the_score_cannot_go_negative(self, tmp_path):
        """A module-level finding names a scope that is not one of the units."""
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            import pytest

            import mypkg.storage as storage

            if not hasattr(storage, "JSON_DIR"):
                pytest.skip("storage layout changed", allow_module_level=True)


            @pytest.mark.skip(reason="flaky")
            def test_writes_the_row():
                assert True
            """,
        )

        result = self_skip_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 0
        assert "2/2 test scopes" in result["checks"][0]["message"]

    def test_three_skips_in_one_unit_cost_that_unit_once(self, tmp_path):
        """One unit is one place a reader has to go and look at."""
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            import pytest

            from mypkg import registry


            @pytest.mark.skipif(not hasattr(registry, "build"), reason="a")
            def test_three_ways():
                if not hasattr(registry, "make"):
                    pytest.skip("b")
                if not hasattr(registry, "form"):
                    pytest.skip("c")
                assert True


            def test_runs_always():
                assert True
            """,
        )

        result = self_skip_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 3
        assert result["score"] == 66

    def test_one_skip_decorator_produces_exactly_one_finding(self, tmp_path):
        """A `@skip()` decorator is seen twice and must be reported once."""
        _write(
            tmp_path,
            "tests/test_alias.py",
            """
            from pytest import skip


            @skip()
            def test_not_written_yet():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert len(rows) == 1
        assert rows[0]["species"] == "PERMA-SKIP"

    def test_the_score_is_clean_scopes_over_total_scopes(self, tmp_path):
        """One flagged unit, four units and one file scope: four of five clean."""
        result = self_skip_check.check_branch(str(_self_skip_project(tmp_path)))

        assert result["score"] == 80
        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "SELF_SKIP"
        assert result["checks"][0]["passed"] is False
        assert "tests/test_skips.py::test_gates_on_the_subject" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = self_skip_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = self_skip_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

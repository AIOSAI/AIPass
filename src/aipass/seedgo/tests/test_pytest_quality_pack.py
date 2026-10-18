# =================== AIPass ====================
# Name: test_pytest_quality_pack.py
# Description: behavioural pins for the pytest_quality standards pack
# Version: 1.4.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/corpus.py and the pack's checkers beside it."""

# Every project here is written into tmp_path: no host fact, live tree or fleet count, so no pin is a change detector.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, e.g. pytest_quality_standards/no_oracle_content.py
# seedgo: no-test-needed(constant) — the manifest text in pytest_quality_standards/pack.json

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, no_oracle_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write


class TestCorpusCollection:
    """Which files and which functions become units - every number rests here."""

    def test_both_pytest_filename_shapes_are_collected(self, tmp_path):
        """pytest collects `test_*.py` AND `*_test.py`, so a generic pack must."""
        _write(tmp_path, "tests/test_leading.py", "def test_leading():\n    assert True")
        _write(tmp_path, "tests/trailing_test.py", "def test_trailing():\n    assert True")

        relpaths = {parsed.relpath for parsed in corpus.build(tmp_path).files}

        assert relpaths == {"tests/test_leading.py", "tests/trailing_test.py"}

    def test_a_vendored_test_file_is_never_collected(self, tmp_path):
        """THE WORST FAILURE MODE: scoring a project on its dependencies."""
        _write(tmp_path, ".venv/lib/site/test_vendored.py", "def test_vendored():\n    assert True")
        _write(tmp_path, "node_modules/pkg/test_dependency.py", "def test_dependency():\n    assert True")
        _write(tmp_path, "tests/test_mine.py", "def test_mine():\n    assert True")

        scanned = corpus.build(tmp_path)

        assert [parsed.relpath for parsed in scanned.files] == ["tests/test_mine.py"]
        assert scanned.unit_count() == 1

    def test_module_level_functions_and_class_methods_are_both_units(self, tmp_path):
        """pytest collects both spellings, so the reader has to see both."""
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            def test_at_module_level():
                assert True

            class TestGrouped:
                def test_in_a_class(self):
                    assert True
            """,
        )

        units = list(corpus.build(tmp_path).units())

        assert [(unit.name, unit.class_name) for unit in units] == [
            ("test_at_module_level", ""),
            ("test_in_a_class", "TestGrouped"),
        ]

    def test_an_async_test_is_a_unit(self, tmp_path):
        """`async def test_*` is a test, and it is a separate AST node type."""
        _write(
            tmp_path,
            "tests/test_async.py",
            """
            def test_sync():
                assert True

            async def test_awaits_the_thing():
                result = await fetch()
                assert result
            """,
        )

        names = {unit.name for unit in corpus.build(tmp_path).units()}

        assert names == {"test_sync", "test_awaits_the_thing"}

    def test_a_syntax_error_lands_in_unparseable_and_is_not_counted_as_clean(self, tmp_path):
        """A broken file must not crash the build NOR read as a clean one."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")
        _write(tmp_path, "tests/test_fine.py", "def test_fine():\n    assert True")

        scanned = corpus.build(tmp_path)

        assert scanned.unparseable == ["tests/test_broken.py"]
        assert [parsed.relpath for parsed in scanned.files] == ["tests/test_fine.py"]
        assert scanned.unit_count() == 1

    def test_a_nodeid_carries_the_class_only_when_there_is_one(self, tmp_path):
        """The nodeid is the coordinate a human uses to open the flagged test."""
        _write(
            tmp_path,
            "tests/test_ids.py",
            """
            def test_at_module_level():
                assert True

            class TestGrouped:
                def test_in_a_class(self):
                    assert True
            """,
        )

        ids = [unit.nodeid for unit in corpus.build(tmp_path).units()]

        assert ids == [
            "tests/test_ids.py::test_at_module_level",
            "tests/test_ids.py::TestGrouped::test_in_a_class",
        ]

    def test_a_fixture_named_like_a_test_is_not_a_unit(self, tmp_path):
        """pytest does not collect a fixture, whatever its name (aipass' policy fixture, fleet green leg 20)."""
        _write(
            tmp_path,
            "tests/test_fix.py",
            """
            import pytest
            from pytest import fixture


            @pytest.fixture(autouse=True)
            def test_policy_stays_in_tmp():
                yield 1


            @fixture
            def test_bare_fixture():
                return 2


            def test_real():
                assert True
            """,
        )

        ids = [unit.nodeid for unit in corpus.build(tmp_path).units()]

        assert ids == ["tests/test_fix.py::test_real"]


class TestOracleReading:
    """The four oracle spellings, and the one shape that is not an oracle."""

    def test_a_with_pytest_raises_is_read_as_an_oracle(self):
        """THE HIGHEST-VALUE PIN. The commonest oracle is not an `assert`."""
        unit = _unit(
            """
            def test_refuses_a_bad_path():
                with pytest.raises(ValueError):
                    resolve("nope")
            """
        )

        assert corpus.oracle_calls_in(unit) == ["pytest.raises"]
        assert corpus.asserts_in(unit) == []
        assert no_oracle_check.has_oracle(unit) is True

    def test_an_assert_anywhere_in_the_body_is_found(self):
        """The oracle can be nested; only the unit's top level is not enough."""
        unit = _unit(
            """
            def test_every_row_is_shaped():
                for row in rows():
                    assert row.width == 3
            """
        )

        assert len(corpus.asserts_in(unit)) == 1
        assert no_oracle_check.has_oracle(unit) is True

    def test_a_mock_assert_method_is_an_oracle_via_the_prefix_rule(self):
        """`assert_*` methods are the unittest and mock spellings of an oracle."""
        unit = _unit(
            """
            def test_writes_the_row(store):
                write_row(store, {"a": 1})
                store.save.assert_called_once_with({"a": 1})
            """
        )

        assert corpus.oracle_calls_in(unit) == ["store.save.assert_called_once_with"]
        assert no_oracle_check.has_oracle(unit) is True

    def test_a_unit_that_verifies_nothing_reads_empty_on_both_readers(self):
        """The negative case - without it, a reader that says yes to everything passes."""
        unit = _unit(
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """
        )

        assert corpus.oracle_calls_in(unit) == []
        assert corpus.asserts_in(unit) == []
        assert no_oracle_check.has_oracle(unit) is False


class TestNomination:
    """Who gets flagged, who is excused, and what evidence rides along."""

    @pytest.mark.parametrize(
        "helper",
        ["_assert_document_is_lawful", "check_shape", "_verify_row", "expect_empty"],
    )
    def test_a_call_to_a_checking_helper_is_not_flagged(self, helper):
        """THE EXEMPTION THAT KEEPS THE STANDARD HONEST: the oracle may be one hop away."""
        unit = _unit(f"def test_the_row_is_shaped_right():\n    {helper}(build_row())")

        assert no_oracle_check.has_oracle(unit) is True

    def test_a_test_that_only_drives_production_code_is_flagged_with_its_calls(self, tmp_path):
        """A nomination must show its work, or a human cannot triage it."""
        _write(
            tmp_path,
            "tests/test_bare.py",
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """,
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert len(rows) == 1
        assert rows[0]["calls"] == ["build_widget", "widget.render"]
        assert rows[0]["call_count"] == 2

    def test_the_flag_names_the_unit_and_the_line_it_lives_on(self, tmp_path):
        """A flag with the wrong coordinates sends a reader to an innocent test."""
        path = _write(
            tmp_path,
            "tests/test_lines.py",
            """
            def test_has_an_oracle():
                assert True


            def test_drives_and_checks_nothing():
                produce_a_value()
            """,
        )
        expected_line = next(
            number
            for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if text.startswith("def test_drives_and_checks_nothing")
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_lines.py::test_drives_and_checks_nothing"]
        assert rows[0]["line"] == expected_line

    def test_a_helper_of_the_same_module_holding_the_asserts_is_the_oracle(self, tmp_path):
        """One call away is still visible (hooks' _reason and ai_mail's _claims shapes, fleet green leg 20)."""
        _write(
            tmp_path,
            "tests/test_helpers.py",
            """
            def _claims(value):
                assert value == 1


            def _produce(value):
                return value


            def test_module_helper_checks():
                _claims(run())


            def test_control_helper_checks_nothing():
                _produce(run())


            class TestGate:
                def _reason(self, result):
                    assert result == "block"

                def test_method_helper_checks(self):
                    self._reason(run())
            """,
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_helpers.py::test_control_helper_checks_nothing"]


def _scored_project(root: Path) -> Path:
    """A four-unit project where exactly one unit has no visible oracle."""
    _write(
        root,
        "tests/test_scored.py",
        """
        def test_asserts():
            assert compute() == 3

        def test_raises():
            with pytest.raises(ValueError):
                compute("bad")

        def test_mock(store):
            save(store)
            store.write.assert_called_once_with(3)

        def test_drives_only():
            compute()
        """,
    )
    return root


class TestBranchCheck:
    """The scoring API: what it reports, and what it refuses to report."""

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["advisory"] is True
        assert "nothing measured" in result["checks"][0]["message"]

    def test_the_score_is_the_share_of_units_with_a_visible_oracle(self, tmp_path):
        """The number is units-WITH-an-oracle over total, not the inverse."""
        result = no_oracle_check.check_branch(str(_scored_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_scored.py::test_drives_only"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - the pack scores before it is calibrated."""
        result = no_oracle_check.check_branch(str(_scored_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["checks"][0]["passed"] is False
        assert "no visible oracle" in result["checks"][0]["message"]

    def test_an_unparseable_file_is_named_as_not_measured(self, tmp_path):
        """A file that could not be read must never pass for a clean one."""
        _scored_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = no_oracle_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


class TestTheFixesFromTheFirstRedFirstPass:
    """The two defects the pack's own first test pass found in the pack."""

    def test_a_project_that_keeps_tests_outside_a_top_level_tests_dir_is_still_measured(self, tmp_path):
        """Pins the whole-tree fallback in corpus.build."""
        (tmp_path / "src" / "tests").mkdir(parents=True)
        (tmp_path / "src" / "tests" / "test_a.py").write_text("def test_one():\n    assert 1 == 1\n", encoding="utf-8")
        (tmp_path / "test_root_level.py").write_text("def test_two():\n    assert 2 == 2\n", encoding="utf-8")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result.get("not_applicable") is not True
        assert result["score"] == 100
        assert "2/2" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """Pins: a broken file must never read as an absent one."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_broken.py").write_text("def test_broken(:\n    pass\n", encoding="utf-8")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in c["message"] for c in result["checks"])

    def test_a_genuinely_empty_project_still_says_no_test_files_found(self, tmp_path):
        """The other arm of the same fix - the fallback must not swallow the real empty case."""
        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" in result["checks"][0]["message"]


class TestTheCorpusWalkSurvivesWhereItLives:
    """The portability species: three ways a corpus silently collected nothing."""

    def test_a_project_living_under_a_vendor_named_directory_is_still_walked(self, tmp_path):
        """Pins relative-path pruning in corpus._walk."""
        project = tmp_path / "build" / "myproject"
        (project / "tests").mkdir(parents=True)
        (project / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")

        scanned = corpus.build(project, test_dirs=("tests", "test"))

        assert scanned.unit_count() == 1

    def test_a_vendor_directory_inside_the_project_is_still_pruned(self, tmp_path):
        """The other arm - the fix must not simply stop pruning."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_mine.py").write_text("def test_m():\n    assert 1\n", encoding="utf-8")
        vendored = tmp_path / "node_modules" / "dep" / "tests"
        vendored.mkdir(parents=True)
        (vendored / "test_theirs.py").write_text("def test_t():\n    assert 1\n", encoding="utf-8")

        scanned = corpus.build(tmp_path)

        assert [f.relpath for f in scanned.files] == ["tests/test_mine.py"]

    def test_a_test_file_outside_the_named_test_dirs_is_never_read_as_production(self, tmp_path):
        """Pins that production excludes every test-SHAPED file, not just collected ones."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "test_stray.py").write_text(
            'COMMANDS = ("ghost-verb",)\n\n\ndef test_stray():\n    assert 1\n', encoding="utf-8"
        )

        scanned = corpus.build(tmp_path, test_dirs=("tests", "test"), with_production=True)

        assert scanned.production_trees == {}

    def test_a_real_production_module_is_still_parsed_into_production_trees(self, tmp_path):
        """The other arm - excluding test-shaped files must not exclude everything."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "app.py").write_text('COMMANDS = ("run",)\n', encoding="utf-8")

        scanned = corpus.build(tmp_path, test_dirs=("tests", "test"), with_production=True)

        assert list(scanned.production_trees) == ["app.py"]


class TestTheTeachingTemplatesStillRun:
    """The templates claim to be worked examples. Something has to prove it."""

    def test_every_teaching_template_passes_when_it_is_actually_run(self):
        """Pins that the templates in pytest_quality_standards/templates are green."""
        import subprocess
        import sys

        templates = (
            Path(__file__).resolve().parent.parent / "apps" / "handlers" / "pytest_quality_standards" / "templates"
        )
        assert templates.is_dir(), f"templates directory is missing: {templates}"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(templates),
                "-q",
                "-o",
                "python_files=test_*.py *_test.py",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )

        assert completed.returncode == 0, f"templates are not green:\n{completed.stdout}\n{completed.stderr}"

    def test_the_templates_are_not_collected_by_the_branch_suite(self):
        """Pins the other arm - teaching files must stay OUT of the branch count."""
        templates = (
            Path(__file__).resolve().parent.parent / "apps" / "handlers" / "pytest_quality_standards" / "templates"
        )

        collected_by_branch_pattern = sorted(p.name for p in templates.glob("test_*.py"))

        assert collected_by_branch_pattern == []

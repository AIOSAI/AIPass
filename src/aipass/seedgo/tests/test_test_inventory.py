# =================== AIPass ====================
# Name: test_test_inventory.py
# Description: behavioural pins for the test-inventory verb
# Version: 1.0.5
# Created: 2026-09-01
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/inventory.py and the handlers under apps/handlers/test_inventory/."""

# Every project here is built in tmp_path: no fleet count, Python version or platform, the species the tool exists to find.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; shape only walks the tree it returns
# seedgo: no-test-needed(constant) — COMMANDS and DEFAULT_TOP, the verb's names and its default queue length

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.test_inventory import collection, exclusions, history, ranking, report, shape
from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.test_inventory import roots, twins
from aipass.seedgo.apps.modules import CommandRefused, inventory


def _function(source: str) -> ast.AST:
    """The first function node in a source snippet."""
    return ast.parse(textwrap.dedent(source)).body[0]


def _classify(source: str) -> shape.Shape:
    """The assertion shape of one written-out test function."""
    return shape.classify(_function(source))


class TestAssertionShape:
    """What the NONE / MOCK_ONLY / REAL column convicts, and what it clears."""

    def test_a_function_that_checks_nothing_is_convicted_as_shapeless(self):
        """The planted case. A smoke test that only proves no exception raised."""
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
        """A change detector must not be cleared as a checking test."""
        found = _classify(
            """
            def test_writes_the_row(mock_store):
                write_row(mock_store, {"a": 1})
                mock_store.save.assert_called_once_with({"a": 1})
            """
        )

        assert found.shape == shape.SHAPE_MOCK_ONLY

    def test_a_project_helper_named_assert_something_is_not_read_as_a_mock(self):
        """THE DEFECT: `startswith("assert_")` reads a project helper as a mock."""
        found = _classify(
            """
            def test_the_row_is_shaped_right():
                assert_row_shape(build_row())
            """
        )

        assert found.shape != shape.SHAPE_MOCK_ONLY
        assert found.delegated_oracle is True

    def test_pytest_raises_as_a_context_manager_is_a_real_oracle(self):
        """A test with no `assert` statement can still check something."""
        found = _classify(
            """
            def test_refuses_a_bad_path():
                with pytest.raises(ValueError):
                    resolve("nope")
            """
        )

        assert found.shape == shape.SHAPE_REAL

    def test_the_body_fingerprint_survives_a_new_process(self):
        """THE DEFECT: `hash()` is salted per process (PEP 456)."""
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
        encoding="utf-8",
        timeout=120,
        env={"PYTHONHASHSEED": "random", "PATH": "/usr/bin:/bin"},
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


class TestWhatCountsAsATest:
    """The collection rules, which decide every number in the report."""

    def test_a_helper_class_contributes_no_tests(self, tmp_path):
        """pytest collects methods from `Test*` classes and no others."""
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
        """pytest skips a `Test*` class that defines `__init__`, with a warning."""
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
        """`norecursedirs` carries `.*`, which is what keeps `.archive` out."""
        _write(tmp_path, "tests/.archive/test_old.py", "def test_old():\n    assert True")
        _write(tmp_path, "tests/test_live.py", "def test_live():\n    assert True")

        names = {func.name for func in collection.collect(tmp_path).functions}

        assert names == {"test_live"}

    def test_the_blame_range_starts_at_the_first_decorator(self, tmp_path):
        """A `@parametrize` table is part of the test that carries it."""
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


class TestExclusions:
    """Files pytest refuses to run, and the two mechanisms that do it."""

    def test_a_conftest_ignore_glob_silences_only_its_own_directory(self, tmp_path):
        """THE DEFECT: a basename match silences every `parked/` in the fleet."""
        _write(tmp_path, "tests/parked/conftest.py", 'collect_ignore_glob = ["*"]')
        _write(tmp_path, "tests/parked/test_parked.py", "def test_parked():\n    assert True")
        _write(tmp_path, "tests/other/test_live.py", "def test_live():\n    assert True")

        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)

        assert statuses["tests/parked/test_parked.py"] == exclusions.STATUS_CONFTEST_IGNORE
        assert statuses["tests/other/test_live.py"] == exclusions.STATUS_COLLECTED

    def test_a_directory_in_collect_ignore_silences_the_files_under_it(self, tmp_path):
        _write(tmp_path, "tests/conftest.py", 'collect_ignore = ["legacy"]')
        _write(tmp_path, "tests/legacy/deep/test_old.py", "def test_old():\n    assert True")
        _write(tmp_path, "tests/test_live.py", "def test_live():\n    assert True")

        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)

        assert statuses["tests/legacy/deep/test_old.py"] == exclusions.STATUS_CONFTEST_IGNORE
        assert statuses["tests/test_live.py"] == exclusions.STATUS_COLLECTED

    def test_a_string_testpaths_is_split_on_whitespace_not_into_letters(self, tmp_path):
        _write(tmp_path, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = "tests checks"')

        assert collection.read_rules(tmp_path).testpaths == ("tests", "checks")

    def test_importorskip_is_conditional_and_a_bare_skip_is_not(self, tmp_path):
        """THE MEASURED MISS. Whether an `importorskip` file runs is a HOST fact."""
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
        """THE DEFECT: matching the literal word `pytest` misses an alias."""
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
        """THE DEFECT: porcelain emits the full header ONCE per commit."""
        parsed = history.parse_porcelain(PORCELAIN)

        assert parsed.authors == {1: "Alice", 2: "Alice", 3: "Bob"}
        assert parsed.times[3] == 2000000

    def test_the_author_is_whoever_owns_the_most_lines(self):
        """A one-line fix by a second hand does not re-author the test."""
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
        """A test with no history is a different object from an ordinary one."""
        attributed = history.attribute(history.LineHistory(authors={}, times={}, tracked=False), 1, 10, now=3000000.0)

        assert attributed.author_bucket == history.BUCKET_UNTRACKED
        assert attributed.age_days is None

    def test_an_unrecognised_author_goes_to_other_and_never_to_human(self):
        """THE DEFECT: defaulting unknown names into the smallest bucket."""
        assert history.bucket_for("SomeNewAgent") == history.BUCKET_OTHER
        assert history.bucket_for("AIOSAI") == "AGENT_AIOSAI"


class TestScoring:
    """The composite, and the vocabulary gate around the artifact."""

    def test_every_component_is_visible_and_they_sum_to_the_composite(self):
        """A reader who disagrees with the weighting must be able to re-sort."""
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
        """THE DEFECT: `None` treated as zero days puts untracked files on top."""
        untracked = history.FunctionHistory(
            author="", author_bucket=history.BUCKET_UNTRACKED, age_days=None, days_since_touch=None, lines=0
        )

        scored = ranking.score(_classify("def test_x():\n    assert True"), untracked, twins=1, file_tests=1)

        assert scored.components["recency"]["value"] == 0.0

    def test_publishing_without_blind_spots_is_refused(self):
        """The blind spots are the load-bearing half of an honest report."""
        with pytest.raises(ValueError, match="blind spots"):
            report.assert_publishable({"blind_spots": []})

    def test_a_delete_family_word_in_a_published_label_refuses_the_write(self):
        """THE WHOLE ARGUMENT, defended in code rather than in prose."""
        summary = {
            "blind_spots": ["something"],
            "ranking": {"means": "mentions delete, deliberately, in prose"},
            "bands": {"keep": 1, "dead": 2},
        }

        with pytest.raises(ValueError, match="delete-family"):
            report.assert_publishable(summary)

    def test_values_may_say_the_word_a_key_may_not(self):
        """Test names, file paths and prose are data; only a key is a published category."""
        report.assert_publishable(
            {
                "blind_spots": ["something"],
                "busiest_files": [{"file": "tests/test_remove.py", "tests": 3}],
                "note": "delete",
            }
        )

        with pytest.raises(ValueError, match="delete-family"):
            report.assert_publishable({"blind_spots": ["something"], "delete": 1})

    def test_the_real_published_prose_is_publishable(self):
        """The shipped strings pass their own gate."""
        report.assert_publishable(
            {
                "blind_spots": list(report.BLIND_SPOTS),
                "ranking": {"means": ranking.NEVER_A_DELETE_VERDICT},
                "assertion_shape": {"counts": {"NONE": 1}},
            }
        )


class TestPublication:
    """One small tree, all the way through to files on disk."""

    def test_a_built_tree_publishes_rows_a_summary_and_a_digest(self, tmp_path):
        """The pipeline holds together and writes where it is told."""
        _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True")
        found = collection.collect(tmp_path)
        statuses = exclusions.classify(tmp_path, found.files, found.rules.norecursedirs)
        blames = {relpath: history.LineHistory({}, {}, tracked=False) for relpath in found.files}

        inventory = report.build(tmp_path, found, statuses, blames, now=1_000_000.0)
        paths = report.publish(inventory, directory=tmp_path / "out")

        rows = [json.loads(line) for line in paths["rows"].read_text(encoding="utf-8").splitlines()]
        summary = json.loads(paths["summary"].read_text(encoding="utf-8"))

        assert [row["nodeid"] for row in rows] == ["tests/test_x.py::test_x"]
        assert summary["blind_spots"]
        assert summary["ranking"]["authorises_deletion"] is False
        assert paths["readable"].read_text(encoding="utf-8").startswith("# Test inventory")


def _run_twins_verb(tmp_path: Path, monkeypatch, argument: str) -> list:
    """Run `test-inventory <argument> --twins` and return the containers it handed twins.build."""
    out = tmp_path / "out"
    scratch = tmp_path / "scratch"
    _write(scratch, "alpha/tests/test_a.py", "def test_a():\n    assert 1 + 1 == 2")
    monkeypatch.setattr(report, "ARTIFACT_DIR", out)
    monkeypatch.setattr(twins, "ARTIFACT_DIR", out)
    for module in (inventory, report, twins):
        monkeypatch.setattr(module, "json_handler", MagicMock())
    real_build = twins.build
    seen = []

    def recording_build(container):
        seen.append(container)
        return real_build(scratch)

    monkeypatch.setattr(twins, "build", recording_build)
    assert inventory.handle_command("test-inventory", [argument, "--twins"]) is True
    return seen


class TestTheTopSwitch:
    """`--top N` on the test-inventory verb."""

    def test_top_one_prints_one_queue_row_not_the_default_fifteen(self, tmp_path: Path, monkeypatch, capsys) -> None:
        tree = tmp_path / "tree"
        _write(tree, "tests/test_a.py", "def test_a():\n    assert 1\n\ndef test_b():\n    assert 2\n")
        monkeypatch.setattr(report, "ARTIFACT_DIR", tmp_path / "out")
        for module in (inventory, report):
            monkeypatch.setattr(module, "json_handler", MagicMock())

        assert inventory.handle_command("test-inventory", [str(tree), "--top", "1"]) is True

        out, err = capsys.readouterr()
        assert "does not know the option" not in err
        queue = out.split("Read these first", 1)[1]
        assert "  1. " in queue
        assert "  2. " not in queue


class TestTheTwinsSwitch:
    """`--twins` on the test-inventory verb."""

    def test_the_twins_flag_is_declared_and_parsed(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """`--twins` through the verb runs the twin report over the named target, not the inventory."""
        tree = tmp_path / "tree"
        _write(tree, "alpha/tests/test_a.py", "def test_a():\n    assert 1 + 1 == 2")
        out = tmp_path / "out"
        monkeypatch.setattr(report, "ARTIFACT_DIR", out)
        monkeypatch.setattr(twins, "ARTIFACT_DIR", out)
        for module in (inventory, report, twins):
            monkeypatch.setattr(module, "json_handler", MagicMock())

        assert inventory.handle_command("test-inventory", [str(tree), "--twins"]) is True

        printed = capsys.readouterr().out
        assert "does not know the option" not in printed
        assert "cross-branch twins" in printed
        published = json.loads((out / twins.REPORT_NAME).read_text(encoding="utf-8"))
        assert published["root"] == str(tree)
        assert not (out / report.ROWS_NAME).exists()

    def test_the_fleet_target_walks_the_branch_container_not_the_repo_root(self, tmp_path: Path, monkeypatch) -> None:
        """`inventory._branch_container` descends from the repo root to the branches."""
        fleet = roots.resolve(roots.FLEET_ARGUMENT)
        [container] = _run_twins_verb(tmp_path, monkeypatch, roots.FLEET_ARGUMENT)

        assert container != fleet.path
        assert (container / "seedgo" / "tests").is_dir()

    def test_the_container_is_the_same_on_a_host_with_no_registry(self, tmp_path: Path, monkeypatch) -> None:
        """The fleet container never depends on AIPASS_REGISTRY.json existing."""
        fleet = roots.resolve(roots.FLEET_ARGUMENT)
        [with_registry] = _run_twins_verb(tmp_path / "with", monkeypatch, roots.FLEET_ARGUMENT)

        monkeypatch.setattr(inventory, "_branch_paths", lambda: {})
        monkeypatch.setattr(registry_scan, "find_registry", lambda: tmp_path / "AIPASS_REGISTRY.json")
        [without_registry] = _run_twins_verb(tmp_path / "without", monkeypatch, roots.FLEET_ARGUMENT)

        assert without_registry == with_registry
        assert without_registry != fleet.path
        assert (without_registry / "seedgo" / "tests").is_dir()

    def test_a_directory_target_is_walked_exactly_as_given(self, tmp_path: Path, monkeypatch) -> None:
        """Only the fleet target is redirected; a named directory is not."""
        target = tmp_path / "named"
        target.mkdir()

        assert _run_twins_verb(tmp_path, monkeypatch, str(target)) == [target]

    def test_the_fleet_target_with_no_registry_raises_instead_of_walking_the_cwd(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(registry_scan, "find_registry", lambda: tmp_path / "AIPASS_REGISTRY.json")

        with pytest.raises(FileNotFoundError, match="no registry"):
            roots.resolve(roots.FLEET_ARGUMENT)

    def test_an_unknown_option_is_refused_with_exit_code_seven(self, capsys) -> None:
        with pytest.raises(CommandRefused) as refused:
            inventory.handle_command("test-inventory", ["aipass", "--bogus"])

        assert refused.value.code == 7
        assert "does not know the option '--bogus'" in capsys.readouterr().err

# =================== AIPass ====================
# Name: test_twins_report.py
# Description: behavioural pins for the cross-branch twin report
# Version: 1.0.2
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/test_inventory/twins.py — the cross-branch twin report."""

# Keyed on (name, body fingerprint), never filename: a name-keyed merge collapses diverged bodies and loses coverage.
# Every tree is built under tmp_path; no number comes from the live fleet.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/test_inventory/twins.py parses and imports

import json
import textwrap
from pathlib import Path
from typing import Dict

import pytest

from aipass.seedgo.apps.handlers.test_inventory import twins

#: Two bodies with different statement shapes: the fingerprint drops names and literals, so only statements can differ.
BODY_ONE = "value = 1\n    assert value"
BODY_TWO = "assert True"


def _tree(root: Path, branches: Dict[str, Dict[str, str]]) -> Path:
    """A synthetic fleet: {branch: {test filename: source}} under `root`."""
    for branch, files in branches.items():
        for filename, source in files.items():
            path = root / branch / "tests" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return root


def _test(name: str, body: str = BODY_ONE) -> str:
    """One written-out test function."""
    return f"def {name}():\n    {body}\n"


def _spread(root: Path, name: str, count: int, filename: str = "test_shared.py", body: str = BODY_ONE) -> Path:
    """The same test, written into `count` branches named branch00, branch01..."""
    return _tree(root, {f"branch{index:02d}": {filename: _test(name, body)} for index in range(count)})


def _group_named(report: dict, key: str, name: str) -> dict:
    """The one group under `key` carrying `name`, or a failure that says so."""
    matches = [group for group in report[key] if group["name"] == name]
    assert len(matches) == 1, f"expected exactly one {key} entry for {name}, got {matches}"
    return matches[0]


class TestTwinIdentity:
    """The consolidation unit is (name, body shape) and never one alone."""

    def test_the_same_name_with_a_different_body_is_not_a_twin(self, tmp_path):
        """THE NEGATIVE CONTROL: a diverged body must never be reported as a twin."""
        _tree(
            tmp_path,
            {
                "brancha": {"test_shared.py": _test("test_stamped", BODY_ONE)},
                "branchb": {"test_shared.py": _test("test_stamped", BODY_TWO)},
            },
        )

        report = twins.build(tmp_path)

        assert report["summary"]["tests"] == 2
        assert report["twin_groups"] == []

    def test_two_branches_sharing_a_name_and_a_shape_are_one_twin_group(self, tmp_path):
        """The positive arm: real duplication is found, with both branches named."""
        _spread(tmp_path, "test_stamped", count=2)

        group = _group_named(twins.build(tmp_path), "twin_groups", "test_stamped")

        assert group["branches"] == ["branch00", "branch01"]
        assert group["files"] == ["branch00/tests/test_shared.py", "branch01/tests/test_shared.py"]
        assert group["tests"] == 2

    def test_the_same_shape_under_a_different_name_is_not_a_twin(self, tmp_path):
        """The other half of the gate: shape alone is not an identity."""
        _tree(
            tmp_path,
            {
                "brancha": {"test_shared.py": _test("test_one_thing", BODY_ONE)},
                "branchb": {"test_shared.py": _test("test_another_thing", BODY_ONE)},
            },
        )

        assert twins.build(tmp_path)["twin_groups"] == []

    def test_one_branch_holding_two_copies_is_not_a_cross_branch_twin(self, tmp_path):
        """A twin needs two BRANCHES, not two copies."""
        _tree(
            tmp_path,
            {
                "brancha": {
                    "test_one.py": _test("test_stamped"),
                    "test_two.py": _test("test_stamped"),
                },
                "branchb": {"test_other.py": _test("test_unrelated")},
            },
        )

        assert twins.build(tmp_path)["twin_groups"] == []

    def test_a_group_counts_test_functions_and_not_branches(self, tmp_path):
        """The test count is occurrences, so a doubled branch is visible."""
        _tree(
            tmp_path,
            {
                "brancha": {
                    "test_one.py": _test("test_stamped"),
                    "test_two.py": _test("test_stamped"),
                },
                "branchb": {"test_one.py": _test("test_stamped")},
            },
        )

        group = _group_named(twins.build(tmp_path), "twin_groups", "test_stamped")

        assert group["branch_count"] == 2
        assert group["tests"] == 3


class TestConsolidationCandidates:
    """Only the fleet-wide identities are put forward, and only those."""

    def test_an_identity_below_the_branch_threshold_is_not_a_candidate(self, tmp_path):
        """Narrow duplication stays a twin group and is never a candidate."""
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES - 1)

        report = twins.build(tmp_path)

        assert len(report["twin_groups"]) == 1
        assert report["consolidation_candidates"] == []

    def test_an_identity_at_the_threshold_is_a_candidate(self, tmp_path):
        """The boundary is inclusive, so the threshold means what it says."""
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        candidate = _group_named(twins.build(tmp_path), "consolidation_candidates", "test_stamped")

        assert candidate["branch_count"] == twins.CONSOLIDATION_BRANCHES
        assert candidate["tests"] == twins.CONSOLIDATION_BRANCHES

    def test_groups_are_ordered_widest_spread_first(self, tmp_path):
        """The reading order is branch count descending, not insertion order."""
        _spread(tmp_path, "test_wide", count=4)
        _tree(
            tmp_path,
            {
                "branch00": {"test_narrow.py": _test("test_narrow")},
                "branch01": {"test_narrow.py": _test("test_narrow")},
            },
        )

        report = twins.build(tmp_path)

        assert [group["name"] for group in report["twin_groups"]] == ["test_wide", "test_narrow"]


class TestResidue:
    """Per stamped family, the tests no candidate group stands behind."""

    def _family_tree(self, root: Path) -> Path:
        """Six branches of one stamped family: a shared test and a local one."""
        family = twins.STAMPED_FAMILIES[0]
        return _tree(
            root,
            {
                f"branch{index:02d}": {
                    family: _test("test_stamped") + "\n" + _test(f"test_local_{index}", BODY_TWO),
                }
                for index in range(twins.CONSOLIDATION_BRANCHES)
            },
        )

    def _block(self, report: dict, family: str) -> dict:
        """One family's residue block."""
        return next(block for block in report["residue"] if block["family"] == family)

    def test_a_family_test_outside_every_candidate_group_is_residue(self, tmp_path):
        """Branch-specific behaviour in a stamped family survives the report."""
        self._family_tree(tmp_path)
        family = twins.STAMPED_FAMILIES[0]

        block = self._block(twins.build(tmp_path), family)

        assert block["residue"] == twins.CONSOLIDATION_BRANCHES
        assert sorted(entry["name"] for entry in block["entries"]) == [
            f"test_local_{index}" for index in range(twins.CONSOLIDATION_BRANCHES)
        ]
        assert block["entries"][0]["file"] == f"branch00/tests/{family}"

    def test_a_family_test_inside_a_candidate_group_is_not_residue(self, tmp_path):
        """The covered half is subtracted, so residue is not just the family total."""
        self._family_tree(tmp_path)
        family = twins.STAMPED_FAMILIES[0]

        block = self._block(twins.build(tmp_path), family)

        assert block["tests"] == twins.CONSOLIDATION_BRANCHES * 2
        assert block["covered_by_candidates"] == twins.CONSOLIDATION_BRANCHES
        assert "test_stamped" not in [entry["name"] for entry in block["entries"]]

    def test_an_absent_family_says_so_rather_than_reporting_a_clean_zero(self, tmp_path):
        """A family nobody stamped here and a fully-covered family differ."""
        _spread(tmp_path, "test_stamped", count=2, filename="test_not_a_family.py")

        blocks = twins.build(tmp_path)["residue"]

        assert [block["family"] for block in blocks] == list(twins.STAMPED_FAMILIES)
        assert all(block["present"] is False for block in blocks)
        assert all(block["residue"] == 0 for block in blocks)


class TestNameSpread:
    """The column that proves a name-keyed merge would have been wrong."""

    def test_a_widespread_name_carrying_two_shapes_counts_as_diverged(self, tmp_path):
        """A name is only "identical everywhere" when every body agrees."""
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)
        _tree(tmp_path, {"branch99": {"test_shared.py": _test("test_stamped", BODY_TWO)}})

        spread = twins.build(tmp_path)["name_spread"]

        assert spread["names"] == 1
        assert spread["identical_everywhere"] == 0
        assert spread["diverged"] == 1

    def test_a_widespread_name_with_one_shape_everywhere_is_identical(self, tmp_path):
        """The positive arm, so `diverged` cannot be satisfied by counting all names."""
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        spread = twins.build(tmp_path)["name_spread"]

        assert spread["diverged"] == 0
        assert spread["identical_names"] == ["test_stamped"]


class TestCorpusAndPublication:
    """What counts as a branch, and what the writer refuses to publish."""

    def test_a_directory_with_no_tests_directory_is_not_a_branch(self, tmp_path):
        """The branch denominator is directories that actually hold tests."""
        _spread(tmp_path, "test_stamped", count=2)
        (tmp_path / "docs" / "chapters").mkdir(parents=True)
        (tmp_path / "docs" / "chapters" / "test_notes.py").write_text(_test("test_stamped"), encoding="utf-8")

        report = twins.build(tmp_path)

        assert report["branches"] == ["branch00", "branch01"]
        assert report["summary"]["tests"] == 2

    def test_publishing_without_caveats_is_refused(self, tmp_path):
        """A report whose limitations went missing is never written to disk."""
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))
        report["caveats"] = []

        with pytest.raises(ValueError, match="no caveats"):
            twins.publish(report, directory=tmp_path / "out")

    def test_a_delete_family_word_in_a_published_key_refuses_the_write(self, tmp_path):
        """No key may read as a verdict, because this phase issues none."""
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))
        report["residue"][0]["safe_to_delete"] = []

        with pytest.raises(ValueError, match="delete-family vocabulary"):
            twins.publish(report, directory=tmp_path / "out")

    def test_a_family_filename_containing_a_delete_word_still_publishes(self, tmp_path):
        """The vocabulary rule is on the keys and deliberately not on the data."""
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))

        assert "test_import_dead_cwd.py" in json.dumps(report)

        target = twins.publish(report, directory=tmp_path / "out")

        assert json.loads(target.read_text(encoding="utf-8"))["summary"]["twin_groups"] == 1

    def test_the_published_artifact_carries_the_candidates_and_the_residue(self, tmp_path):
        """The later phase reads a file, not a return value."""
        self_root = _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        target = twins.publish(twins.build(self_root), directory=tmp_path / "out")
        written = json.loads(target.read_text(encoding="utf-8"))

        assert target.name == twins.REPORT_NAME
        assert [group["name"] for group in written["consolidation_candidates"]] == ["test_stamped"]
        assert [block["family"] for block in written["residue"]] == list(twins.STAMPED_FAMILIES)


class TestTheReportRefusesAConfidentZero:
    """`branch_dirs` on a tree with no branches under it."""

    def test_a_root_holding_no_branches_refuses_instead_of_reporting_zero(self, tmp_path: Path) -> None:
        """`twins.branch_dirs` raises on a tree whose children hold no tests/."""
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()

        with pytest.raises(NotADirectoryError, match="container of branches"):
            twins.branch_dirs(tmp_path)

    def test_the_refusal_names_where_the_branches_actually_live(self, tmp_path: Path) -> None:
        """The message carries the cure, because the cure is not guessable."""
        (tmp_path / "src").mkdir()

        with pytest.raises(NotADirectoryError) as raised:
            twins.branch_dirs(tmp_path)

        assert "src/aipass" in str(raised.value)

    def test_one_real_branch_is_still_enough_to_measure(self, tmp_path: Path) -> None:
        """The refusal fires on NONE, never on FEW."""
        (tmp_path / "solo" / "tests").mkdir(parents=True)
        (tmp_path / "solo" / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        (tmp_path / "docs").mkdir()

        assert [name for name, _ in twins.branch_dirs(tmp_path)] == ["solo"]

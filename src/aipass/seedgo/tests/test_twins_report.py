# =================== AIPass ====================
# Name: test_twins_report.py
# Description: behavioural pins for the cross-branch twin report
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Pins for the twin report. Every test here names the contract it holds.

THE ONE THAT MATTERS MOST is `test_the_same_name_with_a_different_body_is_not
_a_twin`. The whole reason this report is keyed on (name, body fingerprint)
rather than on a filename is a fleet measurement: of the test names living in
six or more branches, only a handful still carry the same body everywhere - the
rest were stamped once and then evolved apart. A name-keyed or filename-keyed
merge would collapse those diverged bodies into one and take real coverage with
it, silently. That test is the negative control which proves the gate is shape
and not name, and if it ever passes for the wrong reason the report becomes
exactly the tool it was built to prevent.

NOTHING HERE ASSERTS A FACT ABOUT THIS MACHINE OR THIS FLEET. Every tree is
built under tmp_path and every expected number is derived from what the test
itself wrote. A pin on a live fleet count would go red the next time any
citizen adds a test, which would make this file a tax on the fleet rather than
a guard on the tool.
"""

import json
import textwrap
from pathlib import Path
from typing import Dict

import pytest

from aipass.seedgo.apps.handlers.test_inventory import twins

#: Two bodies with genuinely different statement shapes. The fingerprint drops
#: names and literals, so a "different" body has to differ in its STATEMENTS -
#: anything less would make the negative control pass for the wrong reason.
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


# =============================================================================
# SHAPE IDENTITY - WHAT COUNTS AS A TWIN
# =============================================================================


class TestTwinIdentity:
    """The consolidation unit is (name, body shape) and never one alone."""

    def test_the_same_name_with_a_different_body_is_not_a_twin(self, tmp_path):
        """THE NEGATIVE CONTROL: a diverged body must never be reported as a twin.

        This is the contract the whole module exists for. Two branches stamped
        the same test name; one of them grew a statement the other never did.
        A report that groups them puts a diverged behaviour on a consolidation
        list, and the merge that follows removes coverage nothing will notice
        is gone.
        """
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
        """The positive arm: real duplication is found, with both branches named.

        Without this the negative control above is satisfied by a report that
        finds nothing at all, which would be a tool that always says "no
        duplication" and can never be wrong.
        """
        _spread(tmp_path, "test_stamped", count=2)

        group = _group_named(twins.build(tmp_path), "twin_groups", "test_stamped")

        assert group["branches"] == ["branch00", "branch01"]
        assert group["files"] == ["branch00/tests/test_shared.py", "branch01/tests/test_shared.py"]
        assert group["tests"] == 2

    def test_the_same_shape_under_a_different_name_is_not_a_twin(self, tmp_path):
        """The other half of the gate: shape alone is not an identity.

        The fingerprint is a statement-kind signature, so a two-line assert
        looks the same in a hundred unrelated tests. Grouping on shape alone
        would put every trivially-shaped test in the fleet into one enormous
        group and call it a consolidation candidate.
        """
        _tree(
            tmp_path,
            {
                "brancha": {"test_shared.py": _test("test_one_thing", BODY_ONE)},
                "branchb": {"test_shared.py": _test("test_another_thing", BODY_ONE)},
            },
        )

        assert twins.build(tmp_path)["twin_groups"] == []

    def test_one_branch_holding_two_copies_is_not_a_cross_branch_twin(self, tmp_path):
        """A twin needs two BRANCHES, not two copies.

        A branch that duplicates a test inside itself has a local matter to
        settle. Counting it here would put single-branch duplication on a
        fleet consolidation list, where no other citizen has any stake in it.
        """
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
        """The test count is occurrences, so a doubled branch is visible.

        A group reporting its branch count as its test count would under-state
        exactly the case a consolidation has to handle: a branch carrying the
        stamped test twice, where merging removes two functions and not one.
        """
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


# =============================================================================
# CONSOLIDATION CANDIDATES - THE SIX-BRANCH GATE
# =============================================================================


class TestConsolidationCandidates:
    """Only the fleet-wide identities are put forward, and only those."""

    def test_an_identity_below_the_branch_threshold_is_not_a_candidate(self, tmp_path):
        """Narrow duplication stays a twin group and is never a candidate.

        The threshold is the entire safety margin. A shape shared by five of
        eighteen branches is a shape thirteen branches disagree with, and the
        measurement behind this tool says the disagreement is where the
        branch-specific coverage lives.
        """
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES - 1)

        report = twins.build(tmp_path)

        assert len(report["twin_groups"]) == 1
        assert report["consolidation_candidates"] == []

    def test_an_identity_at_the_threshold_is_a_candidate(self, tmp_path):
        """The boundary is inclusive, so the threshold means what it says.

        Pinned beside the test below it because an off-by-one here is
        invisible: the report would still look right, just quietly refuse to
        put forward the widest identities in the fleet.
        """
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        candidate = _group_named(twins.build(tmp_path), "consolidation_candidates", "test_stamped")

        assert candidate["branch_count"] == twins.CONSOLIDATION_BRANCHES
        assert candidate["tests"] == twins.CONSOLIDATION_BRANCHES

    def test_groups_are_ordered_widest_spread_first(self, tmp_path):
        """The reading order is branch count descending, not insertion order.

        A reader opens this report at the top. If the order were whatever the
        dictionary happened to hold, the first thing read would be arbitrary
        and the widest - most consequential - identity could sit anywhere.
        """
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


# =============================================================================
# THE RESIDUE - WHAT A FILENAME MERGE WOULD DESTROY
# =============================================================================


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
        """Branch-specific behaviour in a stamped family survives the report.

        This is the output the deletion phase reads. A test sharing a stamped
        filename but sharing its shape with nobody is the coverage a
        filename-keyed merge destroys, and it has to be named - as a branch, a
        file and a test - not merely counted.
        """
        self._family_tree(tmp_path)
        family = twins.STAMPED_FAMILIES[0]

        block = self._block(twins.build(tmp_path), family)

        assert block["residue"] == twins.CONSOLIDATION_BRANCHES
        assert sorted(entry["name"] for entry in block["entries"]) == [
            f"test_local_{index}" for index in range(twins.CONSOLIDATION_BRANCHES)
        ]
        assert block["entries"][0]["file"] == f"branch00/tests/{family}"

    def test_a_family_test_inside_a_candidate_group_is_not_residue(self, tmp_path):
        """The covered half is subtracted, so residue is not just the family total.

        A residue that ignored the candidates would report every stamped test
        as must-survive, which is true, useless, and would make the report say
        nothing at all about consolidation.
        """
        self._family_tree(tmp_path)
        family = twins.STAMPED_FAMILIES[0]

        block = self._block(twins.build(tmp_path), family)

        assert block["tests"] == twins.CONSOLIDATION_BRANCHES * 2
        assert block["covered_by_candidates"] == twins.CONSOLIDATION_BRANCHES
        assert "test_stamped" not in [entry["name"] for entry in block["entries"]]

    def test_an_absent_family_says_so_rather_than_reporting_a_clean_zero(self, tmp_path):
        """A family nobody stamped here and a fully-covered family differ.

        Both report a residue of zero and they mean opposite things - "nothing
        to protect" versus "never looked". Publishing `present` is what stops a
        reader taking the second for the first.
        """
        _spread(tmp_path, "test_stamped", count=2, filename="test_not_a_family.py")

        blocks = twins.build(tmp_path)["residue"]

        assert [block["family"] for block in blocks] == list(twins.STAMPED_FAMILIES)
        assert all(block["present"] is False for block in blocks)
        assert all(block["residue"] == 0 for block in blocks)


# =============================================================================
# NAME SPREAD - THE RECEIPT FOR THE GATE
# =============================================================================


class TestNameSpread:
    """The column that proves a name-keyed merge would have been wrong."""

    def test_a_widespread_name_carrying_two_shapes_counts_as_diverged(self, tmp_path):
        """A name is only "identical everywhere" when every body agrees.

        This is the number that justifies the whole design, so it must not be
        computed from the branch spread alone. One branch with a different body
        is enough to make the name unsafe to merge on, and one is what this
        plants.
        """
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)
        _tree(tmp_path, {"branch99": {"test_shared.py": _test("test_stamped", BODY_TWO)}})

        spread = twins.build(tmp_path)["name_spread"]

        assert spread["names"] == 1
        assert spread["identical_everywhere"] == 0
        assert spread["diverged"] == 1

    def test_a_widespread_name_with_one_shape_everywhere_is_identical(self, tmp_path):
        """The positive arm, so `diverged` cannot be satisfied by counting all names.

        Without it, a build that reported every widespread name as diverged
        would pass the test above while destroying the only signal the column
        carries.
        """
        _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        spread = twins.build(tmp_path)["name_spread"]

        assert spread["diverged"] == 0
        assert spread["identical_names"] == ["test_stamped"]


# =============================================================================
# THE CORPUS AND THE REFUSALS
# =============================================================================


class TestCorpusAndPublication:
    """What counts as a branch, and what the writer refuses to publish."""

    def test_a_directory_with_no_tests_directory_is_not_a_branch(self, tmp_path):
        """The branch denominator is directories that actually hold tests.

        Every "how many branches carry this" number is read against the branch
        list. Counting a docs directory or a build artifact as a branch would
        deflate the spread of every identity in the report at once.
        """
        _spread(tmp_path, "test_stamped", count=2)
        (tmp_path / "docs" / "chapters").mkdir(parents=True)
        (tmp_path / "docs" / "chapters" / "test_notes.py").write_text(_test("test_stamped"), encoding="utf-8")

        report = twins.build(tmp_path)

        assert report["branches"] == ["branch00", "branch01"]
        assert report["summary"]["tests"] == 2

    def test_publishing_without_caveats_is_refused(self, tmp_path):
        """A report whose limitations went missing is never written to disk.

        The package's rule, held here for the same reason `report.py` holds it:
        a caveat a reader has to go looking for is a caveat that will not be
        found, and this report's central caveat is that shape identity is not
        behavioural identity.
        """
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))
        report["caveats"] = []

        with pytest.raises(ValueError, match="no caveats"):
            twins.publish(report, directory=tmp_path / "out")

    def test_a_delete_family_word_in_a_published_key_refuses_the_write(self, tmp_path):
        """No key may read as a verdict, because this phase issues none.

        The report names consolidation candidates. A key called `delete_these`
        turns the same list into an instruction, and the instruction would be
        obeyed by a reader who never opened the caveats.
        """
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))
        report["residue"][0]["safe_to_delete"] = []

        with pytest.raises(ValueError, match="delete-family vocabulary"):
            twins.publish(report, directory=tmp_path / "out")

    def test_a_family_filename_containing_a_delete_word_still_publishes(self, tmp_path):
        """The vocabulary rule is on the keys and deliberately not on the data.

        One of the five stamped families is named `test_import_dead_cwd.py` and
        "dead" is in the delete family. A guard that refused the report because
        the fleet chose that filename would have started editing the
        measurement to satisfy itself.
        """
        report = twins.build(_spread(tmp_path, "test_stamped", count=2))

        assert "test_import_dead_cwd.py" in json.dumps(report)

        target = twins.publish(report, directory=tmp_path / "out")

        assert json.loads(target.read_text(encoding="utf-8"))["summary"]["twin_groups"] == 1

    def test_the_published_artifact_carries_the_candidates_and_the_residue(self, tmp_path):
        """The later phase reads a file, not a return value.

        Pinned because `publish` defaults to seedgo's own `.seedgo/`: a caller
        that could not redirect it would make every test here write into the
        branch's real artifact directory, and a publish that dropped either
        block would leave the deletion phase reading a list with no protection
        beside it.
        """
        self_root = _spread(tmp_path, "test_stamped", count=twins.CONSOLIDATION_BRANCHES)

        target = twins.publish(twins.build(self_root), directory=tmp_path / "out")
        written = json.loads(target.read_text(encoding="utf-8"))

        assert target.name == twins.REPORT_NAME
        assert [group["name"] for group in written["consolidation_candidates"]] == ["test_stamped"]
        assert [block["family"] for block in written["residue"]] == list(twins.STAMPED_FAMILIES)


class TestTheReportRefusesAConfidentZero:
    """`branch_dirs` on a tree with no branches under it.

    Live defect, found only by wiring the report to a CLI verb: the fleet
    target resolves to the REPO root, one level above the branches, and
    `branch_dirs` reads immediate children only. The first live run printed
    "0 twins over 0 branches" as a green success. A cross-branch report that
    answers "nothing found" because it was aimed one level off is worse than
    one that fails, so it now refuses.
    """

    def test_a_root_holding_no_branches_refuses_instead_of_reporting_zero(self, tmp_path: Path) -> None:
        """`twins.branch_dirs` raises on a tree whose children hold no tests/.

        The pin is the REFUSAL, not the message: a caller reading a published
        zero cannot tell "measured, found none" from "measured the wrong tree".
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()

        with pytest.raises(NotADirectoryError, match="container of branches"):
            twins.branch_dirs(tmp_path)

    def test_the_refusal_names_where_the_branches_actually_live(self, tmp_path: Path) -> None:
        """The message carries the cure, because the cure is not guessable.

        Someone meeting this error is holding a path that looks right. Naming
        `<repo>/src/aipass` turns the refusal into a fix rather than a puzzle.
        """
        (tmp_path / "src").mkdir()

        with pytest.raises(NotADirectoryError) as raised:
            twins.branch_dirs(tmp_path)

        assert "src/aipass" in str(raised.value)

    def test_one_real_branch_is_still_enough_to_measure(self, tmp_path: Path) -> None:
        """The refusal fires on NONE, never on FEW.

        The counter-arm: a refusal that also fired on a small-but-real tree
        would make the tool unusable on anything but the whole fleet.
        """
        (tmp_path / "solo" / "tests").mkdir(parents=True)
        (tmp_path / "solo" / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
        (tmp_path / "docs").mkdir()

        assert [name for name, _ in twins.branch_dirs(tmp_path)] == ["solo"]

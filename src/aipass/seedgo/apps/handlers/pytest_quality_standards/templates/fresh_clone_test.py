# =================== AIPass ====================
# Name: fresh_clone_test.py
# Description: teaching template - building the world a test reads, instead of asking the host for it
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""TEACHING TEMPLATE - THE FRESH-CLONE TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, branches stamped them, and five of those stamped families
now total 1,411 tests across the fleet. Measured, only 5 of the 48 test-function
names appearing in six or more branches still shared a shape: stamped once, then
every copy drifted somewhere different. This file teaches a SHAPE and shows its
reasoning, so that you write your own fixture around your own world. If you
catch yourself renaming a directory at the top of a copy of this file, stop -
that is the stamping happening again.

WHAT A FRESH-CLONE TEST IS FOR
CI ran on a fresh clone for the first time after eight waves of test work had
landed overnight against Linux-only verification. Two rows went red, and neither
of them was a bug in the code they covered. Their EXPECTED VALUE came from state
a clone does not have.

Both were `self_skip` cures. A skip had stood in front of a test that reads this
machine; the cure removed the skip, correctly; and the assertion underneath it
turned out to depend on the machine. The cure was right. What it uncovered had
been hidden, not absent.

THE FIRST ROW IS THE ONE THIS FILE IS BUILT AROUND, because it was written to be
safe everywhere:

    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
    live = reg.get_resident_branches()
    if projects_tree.is_dir():
        assert set(live) == {"@baud", "@earmark", "@finch", "@aipass_site"}
    else:
        assert live == {}, "no projects/ tree on this machine - nothing may resolve"

The `else` arm is there FOR CI. It never runs in CI. `.gitignore` says
`projects/*` and then `!projects/README.md`, so a clone HAS a `projects/`
directory - the tracked README lives in it - and none of the four project repos.
CI took the first arm, found nothing, and went red on a line written to protect
it. That directory-exists-but-is-empty world is modelled below as
`a_fresh_clone_tree`, and it is the single most useful thing in this file.

THE CURE IS ONE ARGUMENT, and the same file already had it. Twelve lines above
the red row, a green sibling takes `tmp_path`, builds the tree it is about to
read, and calls the same resolver with the tree as an argument. Same function.
One argument. The answer is now the same on every machine that will ever run it.

    a test that BUILDS the world it reads is a test with one oracle.
    a test that ASKS THE HOST for the world has as many oracles as there are
    hosts, and proves none of them.

WHERE THE CLAIM "A FRESH CLONE FINDS NOTHING" BELONGS
Not in an `else` arm. Not in a `skipif`. Not in CI, which you cannot read from
here and cannot debug when it disagrees with you. Make it against an EMPTY
`tmp_path`, as its own collected test, where it is a real claim about the reader
- an implementation that fell back to some global registry when handed an empty
directory would fail it - and where it runs on every machine including yours.
That is `test_a_fresh_clone_tree_yields_no_residents` below.

THE THREE ARMS THE `fresh_clone` RULE READS, and each has a wrong shape here:

  BOTH_WORLDS  - an oracle that is a runtime `if` on the machine.
  DERIVED_EXPECTED - an expected value copied off one checkout.
  IGNORED_PATH - reading a path the repo refuses to ship.

WHEN NOT TO REACH FOR ANY OF THIS
- The path is under `tmp_path`. pytest made that directory and pytest removes
  it; it is the test's own world, whatever it is spelled, and the rule acquits
  it for that reason.
- The test builds the tree it then reads. That is the cure, and the rule reads
  the `mkdir` and the `write_text` as the acquittal they are.
- The path only LOCATES the module under test. Every test that loads a module by
  file path builds a machine-rooted path and claims nothing about the machine.

HOW THIS FILE IS ORGANISED
The subject is defined inline, so the file is self-contained - it imports pytest
and the standard library and nothing else. `_HOST` is a module-level dict holding
the one thing "this machine" has: a projects tree. It is not a toy. A
module-level mapping really is process-global, which is what lets the collected
tests at the bottom put a DIFFERENT world under the same wrong shape and watch it
change its verdict without changing a line of its code. The `wrong_*` and
`right_*` functions are deliberately NOT named `test_*`, so neither pytest nor
this pack's own reader collects them; they are read, and they are executed by the
collected tests against each of the three worlds, which is what proves the wrong
shapes stay green here and go red - or green for the wrong reason - elsewhere.
"""

import json
from pathlib import Path
from typing import Dict, Iterator, Sequence

import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================

#: The directory a project keeps its resident projects in. Ignored by the repo
#: except for one tracked README, which is the whole trap this file teaches.
PROJECTS_DIR_NAME: str = "projects"

#: What THIS MACHINE has. Process-global on purpose: this is the property that
#: lets a collected test swap the world under a wrong shape and watch the same
#: unchanged code reach a different verdict.
_HOST: Dict[str, Path] = {}


def host_projects_tree() -> Path:
    """Where this machine keeps its projects, whatever is or is not there."""
    return _HOST["tree"]


def resident_branches(projects_tree: Path) -> Dict[str, str]:
    """Every sealed project under a GIVEN tree, by @email.

    THE ARGUMENT IS THE CURE, and it is the entire difference between the red
    row and its green sibling. A reader that takes the world it should read can
    be asked about any world - the one a fixture just built, an empty one, a
    clone-shaped one - and answers the same way on every machine.
    """
    if not projects_tree.is_dir():
        return {}
    found: Dict[str, str] = {}
    for registry in sorted(projects_tree.glob("*/registry.json")):
        found[f"@{registry.parent.name}"] = str(registry.parent)
    return found


def live_resident_branches() -> Dict[str, str]:
    """The same reader with the argument taken away - it asks the host instead.

    Zero arguments, and that is the defect in one signature. Nothing about this
    function is wrong; what is wrong is a TEST that calls it and then writes down
    what it happened to return here.
    """
    return resident_branches(host_projects_tree())


# =============================================================================
# THE THREE WORLDS - and the middle one is why this file exists
# =============================================================================


def a_populated_tree(root: Path) -> Path:
    """The developer's machine: a projects tree holding two sealed projects."""
    tree = root / PROJECTS_DIR_NAME
    for name in ("baud", "earmark"):
        (tree / name).mkdir(parents=True)
        (tree / name / "registry.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    return tree


def a_fresh_clone_tree(root: Path) -> Path:
    """A clone: the directory EXISTS and holds nothing that resolves.

    THE TRAP, MODELLED. `projects/*` is ignored and `!projects/README.md` is
    negated back in, so `projects/` is present in every clone and empty of
    projects in all of them. A guard written as `if tree.is_dir()` reads TRUE
    here and walks straight into the arm that expects four residents.

    Any test that protects itself with "does the directory exist" is protecting
    itself against the wrong question. The question is what is IN it.
    """
    tree = root / PROJECTS_DIR_NAME
    tree.mkdir(parents=True)
    (tree / "README.md").write_text("the catalog, and the only tracked file here\n", encoding="utf-8")
    return tree


def no_tree_at_all(root: Path) -> Path:
    """A machine that has never had a projects tree. The third world, and a real one."""
    return root / "a-directory-that-was-never-created"


# =============================================================================
# THE FIXTURE - the world is BUILT, and built where pytest will remove it
# =============================================================================


@pytest.fixture(autouse=True)
def host_is_a_directory_this_test_built(tmp_path: Path) -> Iterator[Path]:
    """Point "this machine" at a tree under `tmp_path`, and put the holder back after.

    THE WORLD IS BUILT IN A FIXTURE. That is the shape to copy: the test below
    does not ask where it is running, it is HANDED a world whose contents it
    knows because something in this file made them. The teardown clears the
    module-level holder so one test's world cannot become the next test's
    surprise - the same restore discipline `host_state` asks for, applied to the
    one piece of global state this file owns.
    """
    _HOST["tree"] = a_populated_tree(tmp_path / "machine")
    yield _HOST["tree"]
    _HOST.clear()


# =============================================================================
# THE WRONG SHAPES - read these first
# =============================================================================


def wrong_a_asserts_in_both_worlds() -> None:
    """WRONG. The oracle is a runtime `if` on the machine, so only one arm ever runs.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader.
    """
    tree = host_projects_tree()
    live = live_resident_branches()

    # THE DEFECT, AND IT IS THE INCIDENT VERBATIM. Two assertions, two different
    # claims, and whichever one this host selects is the only one anybody ever
    # runs. The `else` arm was written FOR the machine that never reaches it.
    if tree.is_dir():
        assert set(live) == {"@baud", "@earmark"}, sorted(live)
    else:
        assert live == {}, "no projects tree on this machine - nothing may resolve"


def wrong_b_pins_what_this_checkout_holds() -> None:
    """WRONG for a quieter reason: the expected value was copied off one machine.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE DEFECT. There is no branch here and nothing conditional, which is what
    # makes it look better than the first shape. It is worse: the list on the
    # right was read off a terminal on one developer's box and typed in.
    assert sorted(live_resident_branches()) == ["@baud", "@earmark"]


# =============================================================================
# THE RIGHT SHAPE - and why it is different
# =============================================================================


def right_a_reads_the_world_it_was_given(projects_tree: Path, expected: Sequence[str]) -> None:
    """RIGHT. One argument, and the expectation names what the caller built.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE CURE, AND IT IS ONE ARGUMENT WIDE. The world arrives from the caller,
    # the expectation arrives from the caller, and the two were made by the same
    # test three lines apart. Nothing here can disagree with a stranger's box,
    # because nothing here asked it anything.
    assert sorted(resident_branches(projects_tree)) == sorted(expected)


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_the_reader_finds_exactly_the_projects_the_fixture_built(tmp_path: Path) -> None:
    """Pins the reader against a tree this test built: two sealed projects in, two @emails out."""
    tree = a_populated_tree(tmp_path / "built-here")

    right_a_reads_the_world_it_was_given(tree, ["@baud", "@earmark"])
    assert resident_branches(tree)["@baud"] == str(tree / "baud")


def test_a_fresh_clone_tree_yields_no_residents(tmp_path: Path) -> None:
    """Pins the fresh-clone claim where it belongs: an empty tree resolves nothing, asserted here rather than in CI.

    THIS IS THE ASSERTION THAT DOES NOT BELONG IN AN `else` ARM. It is a real
    claim about the reader - an implementation that fell back to some global
    registry when handed a tree with no projects in it would fail this line -
    and it runs on every machine, including the one you are reading this on.
    """
    tree = a_fresh_clone_tree(tmp_path / "clone")

    assert tree.is_dir(), "a clone HAS the directory - that is exactly why is_dir() is not a guard"
    right_a_reads_the_world_it_was_given(tree, [])


def test_a_machine_with_no_tree_at_all_also_yields_no_residents(tmp_path: Path) -> None:
    """Pins the third world: an absent directory answers empty rather than raising."""
    right_a_reads_the_world_it_was_given(no_tree_at_all(tmp_path), [])


def test_wrong_a_is_green_here_and_red_on_a_clone(tmp_path: Path) -> None:
    """Proof: wrong_a_asserts_in_both_worlds passes against this machine's tree and fails against a clone's."""
    # GREEN HERE, and it looks like a careful test while it is being green.
    wrong_a_asserts_in_both_worlds()

    # RED ON A CLONE, and this is the measured incident. The directory exists,
    # so `is_dir()` is TRUE, so the first arm runs and finds nothing. The `else`
    # arm - the one written to protect CI - is unreachable in CI.
    _HOST["tree"] = a_fresh_clone_tree(tmp_path / "clone")
    with pytest.raises(AssertionError):
        wrong_a_asserts_in_both_worlds()

    # The right shape reaches the same reader and states what THAT world holds.
    right_a_reads_the_world_it_was_given(_HOST["tree"], [])


def test_wrong_a_is_also_green_for_a_reason_it_never_proved(tmp_path: Path) -> None:
    """Proof: with no tree at all wrong_a passes through its else arm, having checked neither claim."""
    _HOST["tree"] = no_tree_at_all(tmp_path)

    # GREEN AGAIN, through the OTHER arm, and this is the worse half. A reader
    # skimming a passing suite cannot tell which of the two claims was checked,
    # and on this machine neither of them was the one the author cared about.
    wrong_a_asserts_in_both_worlds()

    # One shape, three worlds, and it names what each of them holds.
    right_a_reads_the_world_it_was_given(no_tree_at_all(tmp_path), [])
    right_a_reads_the_world_it_was_given(a_fresh_clone_tree(tmp_path / "clone"), [])
    right_a_reads_the_world_it_was_given(a_populated_tree(tmp_path / "machine2"), ["@baud", "@earmark"])


def test_wrong_b_pins_this_checkout_and_the_clone_disagrees(tmp_path: Path) -> None:
    """Proof: wrong_b_pins_what_this_checkout_holds passes on the fixture's tree and fails once the world changes."""
    # GREEN, because the list was copied off exactly this world.
    wrong_b_pins_what_this_checkout_holds()

    # RED, and nothing about the READER changed - only the machine did. That is
    # the definition of an expected value that was never the test's to state.
    _HOST["tree"] = a_fresh_clone_tree(tmp_path / "clone")
    with pytest.raises(AssertionError):
        wrong_b_pins_what_this_checkout_holds()


def test_the_right_shape_is_the_same_line_on_every_world(tmp_path: Path) -> None:
    """Proof: right_a_reads_the_world_it_was_given is green on all three worlds with no branch and no skip."""
    worlds = (
        (a_populated_tree(tmp_path / "machine3"), ["@baud", "@earmark"]),
        (a_fresh_clone_tree(tmp_path / "clone3"), []),
        (no_tree_at_all(tmp_path), []),
    )

    for tree, expected in worlds:
        right_a_reads_the_world_it_was_given(tree, expected)

    # AND THE PROPERTY THAT MAKES IT A CURE RATHER THAN A COINCIDENCE: no `if`
    # on the filesystem, no skip, no `else` arm nobody runs. Three worlds, three
    # expectations, one assertion, and every one of them built in this file.
    assert len({id(tree) for tree, _ in worlds}) == 3

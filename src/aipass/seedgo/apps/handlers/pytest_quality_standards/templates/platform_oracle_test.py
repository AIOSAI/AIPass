# =================== AIPass ====================
# Name: platform_oracle_test.py
# Description: teaching template - writing a test whose verdict is about the code, not the host
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""TEACHING TEMPLATE - THE PLATFORM-INDEPENDENT TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, branches stamped them, and five of those stamped families
now total 1,411 tests across the fleet. Measured, only 5 of the 48 test-function
names appearing in six or more branches still shared a shape: stamped once, then
every copy drifted somewhere different. This file teaches a SHAPE and shows its
reasoning, so that you write your own assertions about your own code.

THE QUESTION THIS FILE IS ABOUT
Is this test's pass or fail a fact about the code, or a fact about the host it
ran on? A CI matrix ran Linux and Windows for the first time after eight waves
of test work had landed overnight on Linux-only verification. Nobody wrote a bad
test. Everybody wrote down the only platform they could see.

EVERY DIVERGENCE BELOW IS PROVEN ON THIS MACHINE, NOT DESCRIBED
That constraint is the whole reason this file is worth reading. A template that
said "this differs on Windows" and could not show it would be asking you to take
its word, and you would be right not to. So:

  - `PureWindowsPath` and `PurePosixPath` both ship in the standard library on
    every host. Sorting the same two names through each of them, here, on Linux,
    produces two different orders. That is the LISTING_ORDER divergence, run.
  - A SYMLINK stands in for the Windows 8.3 short name. `RUNNER~1` and the long
    directory it points at are the same directory and two different strings,
    which is exactly the property that makes `Path == Path` the wrong operator.
  - The forgiving filesystem and the empty `.filename` are modelled as
    stand-ins, because a Linux kernel will not be talked into ignoring a mode
    bit. Each is a two-line object, and each is handed to BOTH the wrong shape
    and the right one, so the difference between them is measured rather than
    asserted.

THE FIVE SPECIES, AND WHICH TWO COST YOU A SCORE
`platform_oracle` scores two of the five and reports the other three without
scoring them. That split is deliberate: an arm that would convict correct tests
must not move a number. The three reported arms are places to look, not verdicts.

  SCORED - LISTING_ORDER      an ordered equality against a directory listing
  SCORED - MODE_INJECTOR      a failure injected by the filesystem's mood
  reported - OSERROR_ATTRIBUTE   an assertion on an OS-filled exception field
  reported - UNRESOLVED_TMP_PATH an unresolved temp path compared with ==
  reported - SHALLOW_SANDBOX     a sealed cwd whose ancestors are not rooted

HOW THIS FILE IS ORGANISED
The subject is defined inline, so the file is self-contained - it imports pytest
and the standard library and nothing else. The `wrong_*` and `right_*` functions
are deliberately NOT named `test_*`, so neither pytest nor this pack's own reader
collects them; they are read, and they are executed by the collected tests at the
bottom against both a POSIX-shaped world and a Windows-shaped one. That is what
proves the wrong shapes are green HERE and red THERE, which is the only thing
this file is really claiming.
"""

import errno
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, List, Optional
from unittest.mock import patch

import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================

#: What the code under test lays down. Two names, one upper-cased, and that is
#: the entire ingredient list for the LISTING_ORDER divergence.
SKILL_FILES: tuple = ("SKILL.md", "handler.py")

#: The path segment that makes a destination a DEVICE rather than a directory.
#: POSIX answers ENOTDIR for anything under it; Windows has no such rule, which
#: is the whole of the MODE_INJECTOR divergence in one word.
DEVICE_SEGMENT: str = "null"

#: The marker a branch root carries. The fleet's own code manufactures one of
#: these under the real home in five separate places, which is why an upward
#: walk out of a sandbox is not a theoretical concern.
BRANCH_MARKER: str = ".aipass"

#: Where the world a test BUILT stops and the host begins. None means unbounded,
#: which is what production does and what makes the wrong shape below dangerous.
#: A test that needs the "no marked ancestor" half of the matrix sets this to the
#: top of its own tmp_path tree - see the proof of the fifth wrong shape.
WALK_CEILING: Optional[Path] = None


def lay_down_skill(target: Path) -> List[Path]:
    """Write a skill's two files into `target` and answer with what was written."""
    target.mkdir(parents=True, exist_ok=True)
    for name in SKILL_FILES:
        (target / name).write_text(f"# {name}\n", encoding="utf-8")
    return [target / name for name in SKILL_FILES]


def write_delivery_log(destination: Path, record: str, writer: Callable[[Path, str], None], warn) -> bool:
    """Write one record, and REPORT a write failure instead of raising it.

    The contract worth pinning is the second half: an unwritable log is
    reported, not swallowed and not raised. `writer` is the seam - production
    would call `destination.write_text` here, and taking it as an argument is
    what lets the tests below drive both a strict filesystem and a forgiving one
    through the same code.
    """
    try:
        writer(destination, record)
    except OSError as exc:
        warn("delivery log write failed: %s", exc)
        return False
    return True


class ProgramNotFound(Exception):
    """Our own wrapper. The name of the missing program is IN THE MESSAGE.

    That is the whole cure for OSERROR_ATTRIBUTE, and it is a production
    decision rather than a test one: we fill this string on every platform, so a
    test asserting on it is asserting about our code. `.filename` on the
    underlying OSError is filled by the operating system, and the two operating
    systems disagree.
    """


def run_program(name: str, launcher: Callable[[str], None]) -> None:
    """Launch `name`, and wrap a missing binary in our own error."""
    try:
        launcher(name)
    except FileNotFoundError as exc:
        raise ProgramNotFound(f"executable not found: {name}") from exc


def mint_workspace(parent: Path, name: str) -> Path:
    """Create a workspace under `parent` and answer with its RESOLVED path.

    Resolving what it returns is correct, and it is also why a test that
    compares the answer against an unresolved input is testing the runner's
    temp-directory naming scheme rather than this function.
    """
    made = parent / name
    made.mkdir(parents=True, exist_ok=True)
    return made.resolve()


def current_dir() -> Path:
    """The module's OWN cwd seam. Patch THIS by name, not `pathlib.Path.cwd`."""
    return Path.cwd()


def branch_root() -> Path:
    """Walk up from the current directory to the nearest marked ancestor.

    THE WALK IS THE HAZARD, and it is ordinary code doing an ordinary thing.
    Nothing here is wrong. What is wrong is a test that seals `cwd` onto a
    sandbox, lets this walk run, and then asserts on the NAME it comes back
    with - because what stops the walk is whichever ancestor happens to carry
    the marker, and the ancestors of a temp directory are not the same set on
    every host.

    `WALK_CEILING` is the THIRD cure and the reason this file can prove its own
    claim on any runner: a walk that may leave the tree the test built has the
    host in it, so the test declares where the built world ends. Left at None -
    the default, and the shape production ships with - the walk runs to the
    filesystem root, which is the hazard the wrong shape below rides on.
    """
    walking = current_dir()
    while walking != walking.parent:
        if (walking / BRANCH_MARKER).exists():
            return walking
        if WALK_CEILING is not None and walking == WALK_CEILING:
            break
        walking = walking.parent
    return current_dir()


def describe_branch() -> str:
    """The rendered name of the branch we are standing in."""
    return f"Refreshing {branch_root().name.upper()} dashboard..."


# =============================================================================
# THE TWO WORLDS - a POSIX-shaped host and a Windows-shaped one
# =============================================================================


def posix_writer(destination: Path, record: str) -> None:
    """A STRICT filesystem, manufactured here rather than asked of the host.

    CURED 2026-09-08, AND THE CURE IS THIS FILE EATING ITS OWN RULE. The first
    version really wrote to `/dev/null/impossible/log.jsonl` and relied on POSIX
    answering ENOTDIR. On the Windows runner that path is an ordinary creatable
    location under the current drive: the write SUCCEEDED, nothing was reported,
    and the proof of the wrong shape failed - inside the file that teaches
    MODE_INJECTOR, which is the species for exactly that mistake. Both halves of
    the matrix are stand-ins now, so the divergence is DEMONSTRATED rather than
    requested, and this file makes the same claim on every host.
    """
    if DEVICE_SEGMENT in destination.parts:
        raise OSError(errno.ENOTDIR, "Not a directory", str(destination))
    destination.write_text(record, encoding="utf-8")


def forgiving_writer(_destination: Path, _record: str) -> None:
    """A FORGIVING filesystem, which is the Windows half of the matrix.

    Windows ignores POSIX mode bits for the owner and has no `/dev/null`
    directory semantics. A write the author expected to fail simply succeeds,
    so no exception is raised, nothing is reported, and every assertion built
    on the failure reads zero. It is a no-op here for exactly that reason - and
    it is not a hypothesis: the Windows leg of run 34290037771 did precisely
    this to the first version of this file.
    """
    return None


def posix_launcher(name: str) -> None:
    """A POSIX exec failure: the OS fills `.filename` in."""
    raise FileNotFoundError(errno.ENOENT, "No such file or directory", name)


def windows_launcher(_name: str) -> None:
    """A Windows CreateProcess failure: `.filename` is None, and [WinError 2]."""
    raise FileNotFoundError(errno.ENOENT, "[WinError 2] The system cannot find the file specified")


class RecordingWarner:
    """A stand-in for the module logger, so a report can be counted."""

    def __init__(self) -> None:
        """Start with nothing reported."""
        self.calls: List[tuple] = []

    def __call__(self, template: str, *args: Any) -> None:
        """Record one report."""
        self.calls.append((template, *args))


# =============================================================================
# SPECIES 1 - LISTING_ORDER. SCORED.
# =============================================================================


def wrong_a_compares_a_listing_against_an_ordered_literal(flavour) -> None:
    """WRONG. Sorted, and still platform-ordered, because it sorted PATHS.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader. `flavour` is `PurePosixPath` or `PureWindowsPath`, which is
    how the two halves of the matrix are reached from one machine.
    """
    # THE DEFECT, AND IT SURVIVES `sorted()`, WHICH IS WHY PEOPLE MISS IT.
    # `sorted()` over Path OBJECTS uses PurePath.__lt__, which is
    # case-SENSITIVE on POSIX and case-FOLDED under ntpath. The list is in a
    # deterministic order on each host and a DIFFERENT deterministic order on
    # the other one.
    listed = sorted(flavour(name) for name in SKILL_FILES)
    assert [p.name for p in listed] == ["SKILL.md", "handler.py"]


def right_a1_compares_the_set(flavour) -> None:
    """RIGHT, and the cheapest fix: the claim was never about order.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    listed = sorted(flavour(name) for name in SKILL_FILES)
    assert {p.name for p in listed} == {"SKILL.md", "handler.py"}


def right_a2_sorts_the_names_as_strings(flavour) -> None:
    """RIGHT, and the fix to reach for when order IS part of the claim.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # SORT THE STRINGS, NOT THE PATHS. Once `.name` has been taken the objects
    # are ordinary strings, and string order is byte order on every host. The
    # equivalent spelling is `sorted(paths, key=lambda p: p.name)`, which the
    # checker acquits for the same reason: any key at all displaces
    # PurePath.__lt__, and PurePath.__lt__ is the whole hazard.
    assert sorted(p.name for p in (flavour(n) for n in SKILL_FILES)) == ["SKILL.md", "handler.py"]


# =============================================================================
# SPECIES 2 - MODE_INJECTOR. SCORED.
# =============================================================================


def wrong_b_injects_the_failure_through_the_filesystem(writer) -> None:
    """WRONG. The failure is injected by the filesystem's mood, not at a seam.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    warner = RecordingWarner()

    # THE DEFECT. `/dev/null/impossible/...` is null used as a DIRECTORY, which
    # is an ENOTDIR only POSIX has to give. `chmod(0o444)` is the same mistake
    # spelled differently - Windows ignores POSIX mode bits for the owner. On
    # the other half of the matrix the write SUCCEEDS, nothing is reported, and
    # the count below is zero while the code under test is perfectly correct.
    impossible = Path("/dev/null/impossible/log.jsonl")
    write_delivery_log(impossible, "{}", writer, warner)

    assert len(warner.calls) == 1


def right_b_injects_the_failure_at_the_seam(_writer) -> None:
    """RIGHT. The seam raises, so the claim is about the handler and not about the OS.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """

    def refusing_writer(_destination: Path, _record: str) -> None:
        """The seam, made to fail the same way on every host."""
        raise OSError(errno.EACCES, "Permission denied")

    warner = RecordingWarner()

    # THE CURE. The `writer` argument here is a stand-in for what production
    # would spell as `patch("mybranch.module.Path.write_text",
    # side_effect=OSError("disk full"))`. Either way the failure is MANUFACTURED
    # rather than requested from the kernel, so it happens identically on Linux,
    # on Windows, and on the host nobody has tried yet.
    landed = write_delivery_log(Path("anywhere.jsonl"), "{}", refusing_writer, warner)

    assert landed is False
    assert len(warner.calls) == 1
    assert "delivery log write failed" in warner.calls[0][0]


# =============================================================================
# SPECIES 3 - OSERROR_ATTRIBUTE. REPORTED, NOT SCORED.
# =============================================================================


def wrong_c_asserts_on_an_os_filled_attribute(launcher) -> None:
    """WRONG. `.filename` is filled by the operating system, and they disagree.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    with pytest.raises(ProgramNotFound) as caught:
        run_program("no_such_program_xyz", launcher)

    cause = caught.value.__cause__

    # THE DEFECT, AND IT IS AN OVER-REACH RATHER THAN A MISTAKE. The chain and
    # the type below are true everywhere; the author wanted one more fact and
    # took it from the only field that carries it on this host. A Windows
    # CreateProcess failure leaves `.filename` as None.
    assert isinstance(cause, FileNotFoundError)
    assert cause.filename == "no_such_program_xyz"


def right_c_asserts_the_type_the_chain_and_our_own_message(launcher) -> None:
    """RIGHT. The type and the chain hold everywhere; the NAME comes from our wrapper.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    with pytest.raises(ProgramNotFound) as caught:
        run_program("no_such_program_xyz", launcher)

    # THE CURE, AND IT IS STRICTLY STRONGER THAN THE WRONG SHAPE. The claim
    # "which program was missing" is still made - it is just made against a
    # string OUR code wrote, on every platform, instead of against a field the
    # OS filled on one of them. And it now fails if we ever stop naming the
    # program, which is the regression worth catching.
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert "no_such_program_xyz" in str(caught.value)


# =============================================================================
# SPECIES 4 - UNRESOLVED_TMP_PATH. REPORTED, NOT SCORED.
# =============================================================================


def wrong_d_compares_an_unresolved_temp_path(short_name: Path, long_name: Path) -> None:
    """WRONG. `Path == Path` compares TEXT, and a runner's TEMP has two spellings.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    made = mint_workspace(short_name, "workspace")

    # THE DEFECT. The Windows runner hands `tmp_path` out as an 8.3 short name -
    # `C:\\Users\\RUNNER~1\\...` - until something resolves it, and the code
    # under test resolves what it returns. Both sides name the same directory.
    # Neither side is the same string. Here the two spellings are a directory and
    # a dot-dot route back into it, which is the same property, portable, and
    # needs no filesystem feature - see the fixture for what Windows did to the
    # symlink this used to use.
    assert made == short_name / "workspace"
    assert long_name.is_dir()


def right_d_resolves_both_sides(short_name: Path, long_name: Path) -> None:
    """RIGHT. Resolve both sides, or ask the filesystem whether they are one file.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE CURE, IN ITS TWO SPELLINGS. `resolve()` on both sides makes the
    # comparison textual-but-canonical. `os.path.samefile` skips the text
    # entirely and asks the filesystem, which is the stronger claim where the
    # path really must exist. The template line is `tmp_path = tmp_path.resolve()`
    # as the FIRST line of the unit - one line, and every comparison below it is
    # already cured.
    short_name = short_name.resolve()
    made = mint_workspace(short_name, "workspace")

    assert made == (short_name / "workspace").resolve()
    assert os.path.samefile(made, long_name / "workspace")


# =============================================================================
# SPECIES 5 - SHALLOW_SANDBOX. REPORTED, NOT SCORED.
# =============================================================================


def wrong_e_seals_cwd_and_trusts_the_ancestors(sandbox: Path) -> None:
    """WRONG. `cwd` is sealed one level deep. Its ancestors are not sealed at all.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE DEFECT, AND THE PATCH IS NOT THE BUG. `patch("pathlib.Path.cwd")` sets
    # the attribute on the pathlib.Path CLASS; the module holds that same class
    # object and reads `.cwd` off it at call time, so the patch really does take.
    # Path.cwd() returns the sandbox. What then happens is that production walks
    # UP out of the sandbox and stops at whichever ancestor carries the marker -
    # and the name it renders is that ancestor's, not the sandbox's.
    with patch("pathlib.Path.cwd", return_value=sandbox):
        rendered = describe_branch()

    assert rendered == f"Refreshing {sandbox.name.upper()} dashboard..."


def right_e1_patches_the_seam_the_module_owns(sandbox: Path) -> None:
    """RIGHT. Patch the seam that produces the ANSWER, so no walk runs at all.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE CURE THAT MAKES THE TEST SAY WHAT IT MEANT. This unit is about the
    # RENDERING, not about the walk, so it seals the module's own
    # `branch_root()` by name and the walk never happens. A stdlib classmethod
    # one level below the answer left everything between the seam and the answer
    # unsealed; a seam the module owns is exactly as deep as the claim.
    with patch(f"{__name__}.branch_root", return_value=sandbox):
        rendered = describe_branch()

    assert rendered == f"Refreshing {sandbox.name.upper()} dashboard..."


def right_e2_roots_the_sandbox_before_letting_the_walk_run(sandbox: Path) -> None:
    """RIGHT, when the WALK is the claim: put the marker in the sandbox first.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE OTHER CURE, FOR THE UNIT THAT REALLY IS ABOUT THE WALK. Lay the marker
    # down inside the sandbox, and the walk stops on the first iteration with
    # nothing above it able to answer. Now the test exercises the real loop AND
    # cannot escape, on any host, whatever the ancestors of the temp directory
    # happen to be on that runner.
    (sandbox / BRANCH_MARKER).mkdir(parents=True, exist_ok=True)

    with patch(f"{__name__}.current_dir", return_value=sandbox):
        rendered = describe_branch()

    assert rendered == f"Refreshing {sandbox.name.upper()} dashboard..."


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def two_spellings(tmp_path: Path) -> Iterator[tuple]:
    """One directory reachable under two different strings, spelled portably.

    TWO STRINGS, ONE DIRECTORY - that is the whole property an 8.3 short name
    has, and a dot-dot spelling has it on every platform, with no privilege and
    no filesystem feature behind it.

    IT WAS A SYMLINK NAMED RUNNER~1 UNTIL 2026-09-08, and Windows refused it in
    the most on-topic way available: `FileExistsError [WinError 183]`, because
    the 8.3 generator had ALREADY minted `RUNNER~1` for the long directory
    created one line above. The platform collided with the fixture by proving
    the fixture's own thesis. Symlinks also need Developer Mode or privilege
    there (catalog row 14), so the shape was twice unavailable. Nothing about
    the lesson needed either.
    """
    long_name = tmp_path / "runneradmin_long_profile_name"
    long_name.mkdir()
    short_name = long_name / ".." / long_name.name
    yield short_name, long_name


@pytest.fixture
def sandbox_below_a_marked_ancestor(tmp_path: Path) -> Iterator[Path]:
    """A sandbox whose PARENT carries the branch marker.

    This is the asymmetry that made SHALLOW_SANDBOX green on Linux and red on
    Windows, modelled so it can be run here. `/tmp` has no marked ancestor;
    Windows TEMP lives under the user profile, so a temp directory there HAS one.
    The fixture manufactures the Windows arrangement.
    """
    ancestor = tmp_path / "runneradmin"
    (ancestor / BRANCH_MARKER).mkdir(parents=True)
    sandbox = ancestor / "workspace"
    sandbox.mkdir()
    yield sandbox


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_the_two_path_flavours_really_order_the_same_two_names_differently() -> None:
    """Pins the divergence every LISTING_ORDER claim rests on: POSIX and ntpath disagree, run here."""
    # THE PROOF, AND IT NEEDS NO WINDOWS RUNNER. Both flavours ship in the
    # standard library on every host. This is the incident, reproduced on Linux
    # in two lines.
    posix_order = [p.name for p in sorted(PurePosixPath(n) for n in SKILL_FILES)]
    windows_order = [p.name for p in sorted(PureWindowsPath(n) for n in SKILL_FILES)]

    assert posix_order == ["SKILL.md", "handler.py"]
    assert windows_order == ["handler.py", "SKILL.md"]
    assert posix_order != windows_order


def test_wrong_a_is_green_on_this_machine_and_red_on_the_other_half_of_the_matrix() -> None:
    """Proof: the sorted-listing pin passes under PurePosixPath and fails under PureWindowsPath."""
    # GREEN HERE. This is what the author saw, and there was nothing to see.
    wrong_a_compares_a_listing_against_an_ordered_literal(PurePosixPath)

    # RED THERE. Same code under test, same two files laid down, other runner.
    with pytest.raises(AssertionError):
        wrong_a_compares_a_listing_against_an_ordered_literal(PureWindowsPath)


@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
def test_both_right_shapes_hold_on_both_halves_of_the_matrix(flavour) -> None:
    """Pins the LISTING_ORDER cures: the set comparison and the string sort both hold either way."""
    right_a1_compares_the_set(flavour)
    right_a2_sorts_the_names_as_strings(flavour)


def test_lay_down_skill_really_writes_both_names(tmp_path: Path) -> None:
    """Pins the subject the ordering claims are made about: two files, named, present on disk."""
    # THE CLAIM WITHOUT THE ORDER IN IT. This is what the skills row meant to
    # say, and it says it on every host.
    written = lay_down_skill(tmp_path / "new-skill")

    assert {p.name for p in written} == set(SKILL_FILES)
    assert all(p.is_file() for p in written)


def test_wrong_b_is_green_on_a_strict_filesystem_and_red_on_a_forgiving_one() -> None:
    """Proof: the device-path injector passes against a raising writer and fails when the write succeeds."""
    # GREEN AGAINST A STRICT FILESYSTEM, which is manufactured rather than
    # borrowed from this machine: `posix_writer` refuses a device path by its
    # SPELLING, so the green half means the same thing on a runner where that
    # path is ordinary and creatable. It was the real filesystem until the
    # Windows leg of run 34290037771 wrote the file and left the count at zero.
    wrong_b_injects_the_failure_through_the_filesystem(posix_writer)

    # RED THERE. Nothing raised, nothing was reported, and the count is zero -
    # while `write_delivery_log` is behaving perfectly.
    with pytest.raises(AssertionError):
        wrong_b_injects_the_failure_through_the_filesystem(forgiving_writer)


@pytest.mark.parametrize("writer", [posix_writer, forgiving_writer])
def test_right_b_holds_whatever_the_filesystem_would_have_done(writer) -> None:
    """Pins the MODE_INJECTOR cure: a seam that raises makes the same claim on both filesystems."""
    right_b_injects_the_failure_at_the_seam(writer)


def test_wrong_c_is_green_on_a_posix_launcher_and_red_on_a_windows_one() -> None:
    """Proof: the .filename assertion passes when the OS fills it and fails when it hands back None."""
    wrong_c_asserts_on_an_os_filled_attribute(posix_launcher)

    with pytest.raises(AssertionError):
        wrong_c_asserts_on_an_os_filled_attribute(windows_launcher)


@pytest.mark.parametrize("launcher", [posix_launcher, windows_launcher])
def test_right_c_holds_on_either_launcher(launcher) -> None:
    """Pins the OSERROR_ATTRIBUTE cure: type, chain and our own message survive both platforms."""
    right_c_asserts_the_type_the_chain_and_our_own_message(launcher)


def test_wrong_d_fails_the_moment_the_temp_directory_has_two_spellings(two_spellings) -> None:
    """Proof: the unresolved == compares text, so one directory under two names reads as two."""
    short_name, long_name = two_spellings

    # RED, HERE, ON LINUX. There is no Windows in this test at all - only a
    # directory with two names, which is the property the 8.3 short name has.
    with pytest.raises(AssertionError):
        wrong_d_compares_an_unresolved_temp_path(short_name, long_name)


def test_right_d_holds_under_either_spelling(two_spellings) -> None:
    """Pins the UNRESOLVED_TMP_PATH cure: resolve both sides, and samefile for the stronger claim."""
    short_name, long_name = two_spellings

    right_d_resolves_both_sides(short_name, long_name)
    right_d_resolves_both_sides(long_name, long_name)


def test_wrong_e_is_green_in_an_unmarked_sandbox_and_red_under_a_marked_ancestor(
    tmp_path: Path,
    sandbox_below_a_marked_ancestor: Path,
) -> None:
    """Proof: the sealed-cwd pin passes with no marked ancestor and fails when an ancestor answers first."""
    # GREEN IN A WORLD WITH NO MARKED ANCESTOR, and the ceiling is how that world
    # is BUILT rather than hoped for. Until 2026-09-08 this line ran the walk
    # against the real ancestors of tmp_path and asserted the answer a
    # /tmp-shaped host gives; on the Windows runner tmp_path lives under the user
    # profile, an ancestor answered, and the proof went red - the file that
    # teaches SHALLOW_SANDBOX asking the host what the answer should be. With the
    # ceiling at tmp_path the walk cannot leave the tree this test made, so the
    # claim is about the walk on every runner.
    with patch(f"{__name__}.WALK_CEILING", tmp_path):
        wrong_e_seals_cwd_and_trusts_the_ancestors(tmp_path)

    # RED WHERE TEMP LIVES UNDER THE USER PROFILE. Same patch, same production
    # code, and the walk stops at `runneradmin` instead. No ceiling here: the
    # marked ancestor is inside the built tree and answers first, so this half
    # never reaches the host either.
    with pytest.raises(AssertionError):
        wrong_e_seals_cwd_and_trusts_the_ancestors(sandbox_below_a_marked_ancestor)


def test_the_marked_ancestor_is_what_the_walk_actually_returns(sandbox_below_a_marked_ancestor: Path) -> None:
    """Pins the mechanism behind SHALLOW_SANDBOX: with cwd sealed, the walk still answers with the ancestor."""
    # THE CAUSE, NAMED RATHER THAN INFERRED. The patch took - Path.cwd() really
    # is the sandbox - and the answer is still the ancestor's name. Sealing cwd
    # sealed one level. Everything above it was left as the host left it.
    with patch("pathlib.Path.cwd", return_value=sandbox_below_a_marked_ancestor):
        assert Path.cwd() == sandbox_below_a_marked_ancestor
        assert branch_root().name == "runneradmin"


@pytest.mark.parametrize(
    "shape",
    [right_e1_patches_the_seam_the_module_owns, right_e2_roots_the_sandbox_before_letting_the_walk_run],
)
def test_both_right_e_shapes_hold_whether_or_not_an_ancestor_is_marked(
    shape: Callable[[Path], None],
    tmp_path: Path,
    sandbox_below_a_marked_ancestor: Path,
) -> None:
    """Pins the SHALLOW_SANDBOX cures: a module-owned seam and a rooted sandbox both survive a marked ancestor."""
    shape(tmp_path)
    shape(sandbox_below_a_marked_ancestor)


def test_the_wrong_shapes_are_the_ones_this_pack_would_flag() -> None:
    """Pins the file's own claim: every wrong shape above is green on this host, which is why a rule is needed."""
    # THE POINT OF THE WHOLE FILE, IN ONE UNIT. Three of the five wrong shapes
    # pass right here, right now, with no warning of any kind. The fourth needs
    # only a directory with two names and the fifth only a marked ancestor -
    # neither of which any reviewer on this machine would think to arrange. A
    # reviewer reading these on Linux has nothing to react to, and that is what
    # a static rule is for.
    wrong_a_compares_a_listing_against_an_ordered_literal(PurePosixPath)
    wrong_b_injects_the_failure_through_the_filesystem(posix_writer)
    wrong_c_asserts_on_an_os_filled_attribute(posix_launcher)
    # Each of the three runs against a POSIX-shaped STAND-IN, not against this
    # machine. That is the difference between showing a divergence and being
    # subject to one, and it is the line this file crossed once.

# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Registry globs must not widen on a case-insensitive filesystem
# Created: 2026-08-31
# Modified: 2026-09-12
# =============================================

"""Case-insensitive-filesystem defence for every ``*_REGISTRY.json`` walk.

THE DEFECT. On Windows the ``pathlib`` glob matcher folds case, so
``*_REGISTRY.json`` also matches ``*_registry.json``. This repo is full of bait —
237 lowercase files on this machine at the time of writing:
``drone_command_registry.json`` sits directly beside drone's tree, every branch
carries ``.spawn/.template_registry.json`` (pathlib ``*`` matches dotfiles, unlike
the ``glob`` module), and @flow keeps ten ``flow_json/*_registry.json`` plan
counters. Found on ef029782's windows-setup leg, root-caused by @drone.

MACOS IS THE SUBTLER HOST, and this file had it wrong until FPLAN-0554 (macOS
runs 34707762639 and 34707861282, darwin Python 3.13.15). Its VOLUME folds case,
so a lookup by name finds a lowercase twin, but CPython matches a wildcard with
the posix flavour's rule, which is case-sensitive on darwin too. The volume and
the matcher are two facts, and a probe of one predicts nothing about the other.

WHY IT MATTERS HERE. My sites are identity-bearing: they answer "which project is
this" and "which registry names the caller". A command table read as a trust
anchor is the directory-name-as-identity species, back through a different door.

THE INSTRUMENT. These pins run on Linux. ``case_insensitive_fs`` wraps
``Path.glob`` to also yield the case-folded pattern's matches — @devpulse's shape,
and a faithful emulation of the Windows matcher, because the bait that exists on
disk is lowercase. ``folding_volume`` is the other half: lookups by name fold and
wildcards are left to whatever matcher is installed, so alone it is the macOS
world and stacked on the first it is the Windows one. The instrument's own
honesty is pinned two ways: a POSITIVE control that widens a listing *through
the instrument itself* (never through a re-implementation of its logic — that
mistake cost @aipass a pin that proved nothing while visiting zero files), and a
NEGATIVE control proving the instrument can still say no.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest


REAL_GLOB = Path.glob


# ─── Per-platform expectations: two facts, not one ──────────────────────
#
# A MEASUREMENT IS OF AN INSTRUMENT AND A PLATFORM. Round 4 asserted
# `_host_folds_case(...) is False` — a Linux fact stated as a universal — and it
# went red on the real Windows runner (windows-setup, 28ee90d5, run 33431848734).
# The production cure was never wrong; the PIN's premise was.
#
# TWO FACTS, NOT ONE (FPLAN-0554). One table used to answer "does the host fold"
# and the pins predicted the wildcard glob from it. The macOS runner (Python
# 3.13.15) showed those are different questions: its volume folds, so the probe
# found its twin, and its matcher does not, so `*_REGISTRY.json` never saw
# `wrong_registry.json`. Cause true, outcome false, and the link pin asserted a
# connection that does not exist there. The probe had only LOOKED like a glob
# question: 3.13 answers a glob component with no wildcard by os.path.lexists
# (Lib/glob.py 3.13:408, literal_selector), not by matching, while 3.12 matches
# every component (Lib/pathlib.py 3.12 _make_selector), so the same probe asked
# the matcher under 3.12 and the volume under 3.13.
#
#   VOLUME  — does a lookup by name find a file spelled in another case?
#   MATCHER — does a wildcard match a name spelled in another case? Every
#             registry walk in this branch depends on THIS one.
#
# WHICH HALF IS MEASURED WHERE, stated rather than implied:
#   linux  — both MEASURED LIVE every time this file runs here.
#   win32  — DERIVED from the windows-setup reds, and true by NTFS default either
#            way. The matcher row is also run here as an ORACLE: PureWindowsPath
#            carries the win32 matching rule on every host.
#   darwin — volume DELIBERATELY None (formattable either way, folds by default).
#            Matcher False: a property of CPython's posix flavour, not of the
#            volume, derived from the two macOS reds and run here as an ORACLE
#            through PurePosixPath, the flavour darwin uses.
#
# KEYED ON sys.platform, NOT os.name, and this is a considered deviation from the
# fleet shape. os.name collapses darwin into "posix", and default macOS folds
# case — so an os.name VOLUME table would assert False on a folding host, which is
# EXACTLY the species of error round 5 existed to fix. The matcher table would
# survive os.name; it is keyed the same way so one key reads both.
_VOLUME_FOLDS_BY_PLATFORM = {
    "linux": False,
    "win32": True,
    "darwin": None,
}

_MATCHER_FOLDS_BY_PLATFORM = {
    "linux": False,
    "win32": True,
    "darwin": False,
}

_MATCHER_FLAVOUR_BY_PLATFORM = {
    "linux": PurePosixPath,
    "win32": PureWindowsPath,
    "darwin": PurePosixPath,
}


def _expected(table: dict):
    """The table's row for this host, or None where no fixed answer is honest."""
    return table.get(sys.platform, None)


@pytest.fixture
def case_insensitive_fs(monkeypatch):
    """Make ``Path.glob`` match the way the Windows matcher does.

    Yields the real matches, then the matches of the case-folded pattern, without
    duplicates. Only the ``_REGISTRY.json`` suffix carries uppercase in any
    pattern this branch uses, so folding the whole pattern changes exactly the
    thing under test.
    """

    def _folded(self, pattern, *args, **kwargs):
        seen = []
        for found in list(REAL_GLOB(self, pattern, *args, **kwargs)) + list(
            REAL_GLOB(self, pattern.lower(), *args, **kwargs)
        ):
            if found not in seen:
                seen.append(found)
                yield found

    monkeypatch.setattr(Path, "glob", _folded)
    return _folded


_GLOB_MAGIC = re.compile(r"[*?[]")


@pytest.fixture
def folding_volume(monkeypatch):
    """Make this Linux box's VOLUME fold case, leaving the glob MATCHER as it was.

    Alone, that is CPython 3.13 on a default macOS volume. Requested after
    ``case_insensitive_fs`` it is the Windows world, where both halves fold.
      - A lookup by name finds the file whatever its spelling: ``Path.exists``,
        and a glob component with no wildcard, which 3.13 answers with
        ``os.path.lexists`` (``Lib/glob.py`` 3.13:408, ``literal_selector``)
        rather than by matching.
      - A wildcard pattern goes to whatever ``Path.glob`` was installed when this
        fixture ran: the real case-sensitive posix matcher, or the folding
        emulator when that was requested first.
    """
    real_exists = Path.exists
    prior_glob = Path.glob

    def _folded_twin(path):
        try:
            siblings = list(path.parent.iterdir())
        except OSError:
            return None
        return next((s for s in siblings if s.name.lower() == path.name.lower()), None)

    def _exists(self, *args, **kwargs):
        return real_exists(self, *args, **kwargs) or _folded_twin(self) is not None

    def _glob(self, pattern, *args, **kwargs):
        if _GLOB_MAGIC.search(pattern) or "/" in pattern:
            yield from prior_glob(self, pattern, *args, **kwargs)
            return
        if _exists(self / pattern):
            yield self / pattern

    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(Path, "glob", _glob)


def _volume_folds_case(directory: Path) -> bool:
    """Does THIS VOLUME find a file by a name spelled in another case? Measured.

    Writes ``aipass_case_probe`` and looks up the UPPERCASE spelling — the
    defect's direction (an uppercase name reaching a lowercase file), not a
    generic folding question. A lookup, never a glob: a glob with no wildcard is a
    lookup under 3.13 and a match under 3.12, so the round-5 probe asked a
    different question depending on the interpreter. A probe rather than
    ``sys.platform``, because folding is a property of the VOLUME — macOS folds by
    default and is case-sensitive when formatted that way, and a mounted volume can
    disagree with its own host. Never skipif: a skip retires the assertion on
    exactly the platform whose CI found the defect.
    """
    marker = directory / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    try:
        return (directory / "AIPASS_CASE_PROBE").exists()
    finally:
        marker.unlink()


def _matcher_folds_case(directory: Path) -> bool:
    """Does the glob MATCHER fold case? The fact every registry walk depends on.

    Same marker, globbed through a WILDCARD in the defect's direction, so it takes
    the selector ``*_REGISTRY.json`` takes on every interpreter. On the macOS
    runner the wildcard glob saw nothing while the lookup-shaped probe said
    folding; predicting a wildcard from the volume is what FPLAN-0554 cured.
    """
    marker = directory / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    try:
        return bool(list(directory.glob("*_CASE_PROBE")))
    finally:
        marker.unlink()


def test_the_volume_probe_agrees_with_a_direct_stat(tmp_path):
    """The volume probe's own control. ``Path.exists`` and ``os.path.exists`` are
    two doors to one lookup, so they must agree, or the probe is reporting a
    property of pathlib rather than of the volume. Its first spelling compared a
    no-wildcard glob with ``exists``, which under 3.12 compares the matcher with
    the volume and holds only where those two happen to agree."""
    marker = tmp_path / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    by_stat = os.path.exists(tmp_path / "AIPASS_CASE_PROBE")
    marker.unlink()
    assert _volume_folds_case(tmp_path) is by_stat


def test_the_two_probes_ask_different_questions(tmp_path, folding_volume):
    """The crux of FPLAN-0554, manufactured here: a folding volume under a
    case-sensitive matcher. On the Mac they disagree, so neither probe may stand
    in for the other."""
    assert _volume_folds_case(tmp_path) is True
    assert _matcher_folds_case(tmp_path) is False


def _decoy(directory: Path, name: str = "wrong_registry.json") -> Path:
    """A lowercase counter file that MAPS TO A WRONG IDENTITY.

    Carries a full, well-formed ``branches`` list naming @impostor. That is
    deliberate: it makes every assertion below about *who the mail would land as*
    rather than about set membership, so a pin cannot pass merely because the
    file was filtered out of some list nobody reads.
    """
    seat = directory / "impostor"
    seat.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        json.dumps({"branches": [{"name": "IMPOSTOR", "email": "@impostor", "path": str(seat)}]}),
        encoding="utf-8",
    )
    return path


def _real_registry(directory: Path, name: str = "PROJECT_REGISTRY.json") -> Path:
    seat = directory / "genuine"
    seat.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        json.dumps({"branches": [{"name": "GENUINE", "email": "@genuine", "path": str(seat)}]}),
        encoding="utf-8",
    )
    return path


def _claims_of_the_negative_control(directory: Path) -> None:
    """The negative control's claims, run on the host and in every emulated world."""
    from aipass.ai_mail.apps.handlers.paths import registries_in

    decoy = _decoy(directory)

    if _matcher_folds_case(directory):
        assert decoy in list(directory.glob("*_REGISTRY.json")), (
            "the matcher was probed as case-folding, so the raw glob must see the decoy"
        )
    else:
        assert list(directory.glob("*_REGISTRY.json")) == [], (
            "the matcher was probed as case-sensitive, so the raw glob must not see the decoy"
        )
    assert registries_in(directory) == [], (
        "wherever the matcher folds, the reader is the ONLY thing standing between "
        "a counter file and the caller — and it refuses it on every host"
    )


def _claims_of_the_link(directory: Path) -> None:
    """The link's claims: the raw glob follows the MATCHER probe, the reader refuses either way."""
    from aipass.ai_mail.apps.handlers.paths import registries_in

    folds = _matcher_folds_case(directory)
    decoy = _decoy(directory)

    assert (decoy in list(directory.glob("*_REGISTRY.json"))) is folds
    assert registries_in(directory) == [], "the reader refuses the counter on any filesystem"


class TestTheInstrumentIsHonest:
    """Controls. A widening emulator that never widens turns every pin below
    green for the wrong reason, and a control that cannot fail is not a control."""

    def test_positive_control_the_instrument_really_widens_a_listing(self, tmp_path, case_insensitive_fs):
        """Exercises THE INSTRUMENT, not a copy of its logic.

        The assertion runs the same ``Path.glob`` production code runs. @aipass
        lost a night to a control that re-implemented the matching inline and
        reported success while the walk visited zero files.
        """
        _decoy(tmp_path)
        matched = list(tmp_path.glob("*_REGISTRY.json"))
        assert [p.name for p in matched] == ["wrong_registry.json"], (
            "the instrument must make the lowercase decoy visible to an uppercase pattern"
        )

    def test_negative_control_the_instrument_can_say_no(self, tmp_path):
        """Same fixture tree, instrument NOT installed.

        The claim is that the EMULATOR is what widens the listing above. Under a
        case-sensitive matcher that reads as "the raw glob finds nothing". On
        Windows the raw glob finds the decoy by itself — the matcher folds, which
        is the entire defect these pins exist for — so the original spelling of
        this control failed on the windows-setup leg of ebb8075d asserting `== []`
        against a real WindowsPath.

        So the host is PROBED, never assumed and never skipif'd (@memory's
        ruling, applied fleet-wide 2026-08-31). The probe used to ask the VOLUME,
        and the macOS runner answered yes while its matcher said no (FPLAN-0554,
        runs 34707762639 and 34707861282), so it now asks the MATCHER, the
        question this glob actually puts. Either way the reader refuses the decoy
        and the control can still say no; @spawn's CONTROL_LIVE probe could not
        until a mutant caught it lying.
        """
        _claims_of_the_negative_control(tmp_path)

    def test_the_probe_reports_folding_when_the_host_folds(self, tmp_path, case_insensitive_fs):
        """The Windows branch of the control above never executes on Linux, so
        it would ship unverified. Driven here through the emulator: with a
        folding matcher installed the probe must SAY so, and the production
        reader must still refuse the decoy that the raw glob now hands it.

        This is the assertion that actually ran red on the windows-setup leg —
        reproduced on Linux rather than left to the next CI train to discover.
        """
        assert _matcher_folds_case(tmp_path) is True

        from aipass.ai_mail.apps.handlers.paths import registries_in

        decoy = _decoy(tmp_path)
        assert decoy in list(tmp_path.glob("*_REGISTRY.json"))
        assert registries_in(tmp_path) == []

    def test_cause_the_volume_folds_exactly_as_its_platform_row_says(self, tmp_path):
        """CAUSE, volume half. What this filesystem does, against the table.

        Round 4 wrote `is False` here and CI proved that is a Linux fact, not a
        universal. A platform whose row is None (macOS, formattable either way)
        asserts nothing here — the matcher pins still run there.
        """
        expected = _expected(_VOLUME_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: volume case-folding is configurable — the matcher pins still run")
        assert _volume_folds_case(tmp_path) is expected

    def test_cause_the_matcher_folds_exactly_as_its_platform_row_says(self, tmp_path):
        """CAUSE, matcher half, the one the registry walks depend on. Every known
        platform has a fixed row, darwin included: the matcher follows CPython's
        path flavour, not the volume, so the Mac runs this pin for real."""
        expected = _expected(_MATCHER_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: no matcher row for this platform — see the LINK pin")
        assert _matcher_folds_case(tmp_path) is expected

    def test_outcome_the_raw_glob_sees_the_decoy_exactly_when_the_matcher_row_says_so(self, tmp_path):
        """OUTCOME. What that means for the thing under test: whether an
        uppercase pattern reaches the lowercase counter file. Predicted from the
        MATCHER row; it was the volume row, the prediction the macOS runner
        refuted."""
        expected = _expected(_MATCHER_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: no matcher row for this platform — see the LINK pin")
        decoy = _decoy(tmp_path)
        assert (decoy in list(tmp_path.glob("*_REGISTRY.json"))) is expected

    @pytest.mark.parametrize("platform", sorted(_MATCHER_FOLDS_BY_PLATFORM))
    def test_the_matcher_row_is_what_that_platforms_path_flavour_does(self, platform):
        """ORACLE. Both path flavours ship in the standard library on every host,
        so the matcher row of a platform this box is not can still be run here.
        ``PurePath.match`` and the glob matcher take their case rule from the same
        flavour, and darwin's flavour is posix: its row is False whatever its
        volume does, which is the half the old single table could not say."""
        flavour = _MATCHER_FLAVOUR_BY_PLATFORM[platform]
        assert flavour("wrong_registry.json").match("*_REGISTRY.json") is _MATCHER_FOLDS_BY_PLATFORM[platform]

    def test_link_the_outcome_follows_from_the_cause_on_every_platform(self, tmp_path):
        """LINK. Holds with NO platform row at all: whatever this host does, the
        glob's behaviour must follow from the MATCHER probe's verdict, and the
        production reader must refuse the counter EITHER WAY. It followed the
        volume probe until the macOS runner showed a host where the two disagree.

        A future red then names its own mechanism — a cause pin red means a table
        is wrong about the platform, the outcome pin red means glob disagrees with
        the matcher row, link red means the two are no longer connected at all.
        """
        _claims_of_the_link(tmp_path)

    def test_the_windows_row_is_driven_here_so_it_cannot_rot(self, tmp_path, case_insensitive_fs, folding_volume):
        """The win32 rows are derived, so on Linux they would sit unexecuted
        between Windows CI runs. @prax's rule: emulate the PLATFORM, not just the
        denial.

        Both halves are emulated, stacked: a folding matcher, then a folding
        volume over it. The probes must present Windows, and the negative control
        and the link must hold there with the same claims they make on the host.
        """
        assert _VOLUME_FOLDS_BY_PLATFORM["win32"] is True
        assert _MATCHER_FOLDS_BY_PLATFORM["win32"] is True

        assert _volume_folds_case(tmp_path) is True, "emulated Windows must present a folding volume"
        assert _matcher_folds_case(tmp_path) is True, "emulated Windows must present a folding matcher"

        _claims_of_the_negative_control(tmp_path)
        _claims_of_the_link(tmp_path)

    def test_the_mac_row_is_driven_here_so_it_cannot_rot(self, tmp_path, folding_volume):
        """The two macOS reds, reproduced on Linux before they were cured: a
        folding volume under a case-sensitive matcher. With the old single probe
        the negative control and the link failed in this world with the runner's
        own text ("host was probed as case-folding, so the raw glob must see the
        decoy", and ``in []) is True``). Now the volume folds, the matcher does
        not, the raw glob sees nothing, and the reader refuses the counter anyway.
        """
        assert _MATCHER_FOLDS_BY_PLATFORM["darwin"] is False

        assert _volume_folds_case(tmp_path) is True, "emulated macOS must present a folding volume"
        assert _matcher_folds_case(tmp_path) is False, "emulated macOS must present a case-sensitive matcher"

        _claims_of_the_negative_control(tmp_path)
        _claims_of_the_link(tmp_path)

    def test_darwin_is_deliberately_unfixed_not_forgotten(self, tmp_path):
        """A None row looks like an omission, so it is pinned as a decision.

        Giving darwin a fixed VOLUME row survives every other mutant in this file
        on Linux — there is no Darwin runner here to contradict it — so without
        this pin the table could acquire a false macOS expectation and nothing
        would notice until a Mac ran it. macOS is formattable either way AND
        folds by default, which is why no fixed answer is honest.

        The MATCHER row is the opposite case, pinned beside it so the two are
        never collapsed into one table again: fixed False, because that is
        CPython's posix flavour speaking, whatever the volume was formatted as.

        This is also why the tables key on sys.platform rather than os.name: the
        fleet shape says os.name, but that collapses darwin into "posix" and
        would assert a False volume on a folding host.
        """
        assert _VOLUME_FOLDS_BY_PLATFORM["darwin"] is None
        assert "darwin" in _VOLUME_FOLDS_BY_PLATFORM, "an absent key and a None row read the same at runtime"
        assert _MATCHER_FOLDS_BY_PLATFORM["darwin"] is False

    def test_the_fixtures_never_write_case_twins(self, tmp_path):
        """@memory's round-4 lesson, applied to my own fixtures: a case-twin
        decoy cannot COEXIST on a folding filesystem — it OVERWRITES. A probe or
        fixture that writes twins measures an overwrite while claiming to
        measure case-globbing.

        Mine do not (`wrong_registry.json` vs `PROJECT_REGISTRY.json`, and the
        host probe unlinks its marker), and that is pinned rather than trusted,
        because it is silent on Linux and destructive on Windows.
        """
        decoy = _decoy(tmp_path)
        real = _real_registry(tmp_path)

        assert decoy.name.lower() != real.name.lower(), "fixtures would collide on a folding host"
        assert decoy.exists() and real.exists()
        assert len({decoy.name.lower(), real.name.lower()}) == 2

    def test_the_decoy_would_genuinely_seat_the_wrong_citizen(self, tmp_path):
        """The decoy is a real registry naming a real branch. Without this, a
        green pin might only mean 'the file was skipped', not 'the wrong citizen
        was never reachable'."""
        decoy = _decoy(tmp_path)
        loaded = json.loads(decoy.read_text(encoding="utf-8"))
        assert loaded["branches"][0]["email"] == "@impostor"


class TestFindProjectRootIgnoresLowercaseCounters:
    """``paths.find_project_root`` answers 'which project is this' for the
    cross-project delivery fence (delivery.py:379/383). A wrong root there makes
    the fence compare two different questions."""

    def test_a_lowercase_counter_does_not_become_a_project_root(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.paths import find_project_root

        project = tmp_path / "project"
        _real_registry(project)
        nested = project / "branch" / "apps"
        nested.mkdir(parents=True)
        _decoy(nested.parent)  # branch/wrong_registry.json — closer than the real one

        assert find_project_root(nested) == project

    def test_the_real_registry_is_still_found(self, tmp_path, case_insensitive_fs):
        """The other half. A filter that refuses everything passes every
        did-not-pick-the-decoy assertion in this file."""
        from aipass.ai_mail.apps.handlers.paths import find_project_root

        project = tmp_path / "project"
        _real_registry(project)
        nested = project / "branch" / "apps"
        nested.mkdir(parents=True)

        assert find_project_root(nested) == project

    def test_an_external_project_registry_named_after_itself_survives(self, tmp_path, case_insensitive_fs):
        """SUFFIX only, never the stem. External projects name registries after
        themselves — Vera-Studio_REGISTRY.json, vera_studio_REGISTRY.json — and a
        filter keyed on the stem would delete real citizens to fix a bug."""
        from aipass.ai_mail.apps.handlers.paths import find_project_root

        for stem in ("Vera-Studio", "vera_studio", "feel_good_app"):
            project = tmp_path / stem
            _real_registry(project, f"{stem}_REGISTRY.json")
            nested = project / "src" / "seat"
            nested.mkdir(parents=True)
            assert find_project_root(nested) == project, f"{stem}_REGISTRY.json must resolve"


class TestCallerRegistryNeverResolvesToACounter:
    """``branch_detection._find_caller_registry`` picks the registry that NAMES
    the caller. It returns the FIRST non-AIPass registry it meets walking up, so
    a decoy does not merely add a candidate — it ends the walk."""

    def test_the_impostor_registry_is_never_returned(self, tmp_path, monkeypatch, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.users import branch_detection as bd

        project = tmp_path / "project"
        real = _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")

        assert bd._find_caller_registry() == real

    def test_a_caller_identity_lookup_does_not_seat_the_impostor(self, tmp_path, monkeypatch, case_insensitive_fs):
        """The assertion that is about WHO, not about which file. Both registries
        are well-formed and both name a branch; only one of them is real."""
        from aipass.ai_mail.apps.handlers.users import branch_detection as bd

        project = tmp_path / "project"
        _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")

        assert bd._lookup_branch_by_name("impostor") is None
        assert bd._lookup_branch_by_name("genuine") is not None


class TestReplyPathValidationIsNotSatisfiedByACounter:
    """``reply._validate_reply_path`` guards delivery TOWARD an external project.
    It is existence-only, so a decoy anywhere up the chain is a full pass — this
    is the outbound direction of the same defect."""

    def test_a_counter_ancestor_does_not_validate_a_reply_path(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.email.reply import _validate_reply_path

        stray = tmp_path / "not-a-project"
        _decoy(stray)
        inbox = stray / "seat" / ".ai_mail.local" / "inbox.json"
        inbox.parent.mkdir(parents=True)
        inbox.write_text("{}", encoding="utf-8")

        allowed, reason = _validate_reply_path(str(inbox))
        assert allowed is False
        assert "REGISTRY" in reason

    def test_a_real_registry_ancestor_still_validates(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.email.reply import _validate_reply_path

        project = tmp_path / "project"
        _real_registry(project)
        inbox = project / "seat" / ".ai_mail.local" / "inbox.json"
        inbox.parent.mkdir(parents=True)
        inbox.write_text("{}", encoding="utf-8")

        allowed, reason = _validate_reply_path(str(inbox))
        assert allowed is True, reason


class TestResidentAndProjectTreeDiscovery:
    """The two sites @drone's sweep did not list. Both are one or two levels
    down rather than a walk up, and both decide WHICH CITIZENS EXIST — the
    resident roster and the verified-admin cross-project bridge."""

    def test_resident_discovery_skips_lowercase_counters(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.registry.read import resident_registry_paths

        projects = tmp_path / "projects"
        real = _real_registry(projects / "Genuine")
        _decoy(projects / "Counterfeit")

        assert resident_registry_paths(tmp_path) == [real]

    def test_project_tree_bridge_never_admits_the_impostor(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.registry.read import get_project_tree_branches

        projects = tmp_path / "projects"
        _real_registry(projects / "Genuine")
        _decoy(projects / "Counterfeit")

        found = get_project_tree_branches(tmp_path)
        assert "@impostor" not in found, "the admin bridge must not gain a citizen from a counter file"
        assert "@genuine" in found

    def test_caller_project_branches_skips_the_counter(self, tmp_path, case_insensitive_fs):
        from aipass.ai_mail.apps.handlers.registry.read import get_caller_project_branches

        project = tmp_path / "project"
        _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        found = get_caller_project_branches(str(caller))
        assert "@impostor" not in found
        assert "@genuine" in found


class TestNoInlineRegistryGlobSurvivesInTheTree:
    """The drift guard. Six sites were fixed; the seventh is the one written next
    month by someone who never read this file, so the ban is structural rather
    than remembered."""

    HANDLERS = Path(__file__).resolve().parents[1] / "apps"
    READER_FILE = "paths.py"

    @staticmethod
    def _mentions_registry(arg, module_constants):
        """Whether this glob argument carries a registry pattern.

        TWO spellings, because only catching the first would have let my own fix
        through: ``resident_registry_paths`` globbed
        ``projects.glob(RESIDENT_REGISTRY_GLOB)``, a NAME, and a literal-only ban
        reported that site clean while it held the defect. A rule blind to the
        shape the code actually uses is worse than no rule, because it reports a
        swept tree.
        """
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return "registry" in arg.value.lower()
        if isinstance(arg, ast.Name):
            return "registry" in arg.id.lower() or "registry" in str(module_constants.get(arg.id, "")).lower()
        return False

    def _registry_glob_calls(self):
        """Every ``.glob(...)``/``.rglob(...)`` reaching for a registry pattern,
        outside the one filtered reader."""
        offenders = []
        for source in self.HANDLERS.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            constants = {
                target.id: node.value.value
                for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in ("glob", "rglob"):
                    continue
                for arg in node.args:
                    if self._mentions_registry(arg, constants):
                        offenders.append((source.name, node.lineno, ast.unparse(arg)))
        return offenders

    def test_the_ban_is_measured_not_asserted(self):
        """Positive control for the AST walk itself. If the parser visits nothing
        — wrong root, renamed package — the ban below passes vacuously and
        reports a clean tree it never read."""
        seen = [s.name for s in self.HANDLERS.rglob("*.py")]
        assert len(seen) > 20, f"the walk must actually reach the handler tree, saw {len(seen)}"
        assert self.READER_FILE in seen

    def test_the_ban_catches_a_named_constant_not_only_a_literal(self):
        """Negative control for the RULE. Feeds the matcher the exact shape my
        own resident-discovery site used — a bare Name — and requires a
        conviction. Without this, tightening the ban to literals-only would pass
        every test in this class while reopening the hole."""
        module_constants = {"RESIDENT_REGISTRY_GLOB": "*/*_REGISTRY.json"}

        def _first_arg(source):
            statement = ast.parse(source).body[0]
            assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
            return statement.value.args[0]

        by_name = _first_arg("d.glob(RESIDENT_REGISTRY_GLOB)")
        by_literal = _first_arg('d.glob("*_REGISTRY.json")')
        innocent = _first_arg('d.glob("*.json")')

        assert self._mentions_registry(by_name, module_constants) is True
        assert self._mentions_registry(by_literal, {}) is True
        assert self._mentions_registry(innocent, {}) is False

    def test_only_the_shared_reader_globs_for_registries(self):
        offenders = [o for o in self._registry_glob_calls() if o[0] != self.READER_FILE]
        assert offenders == [], (
            "registry globs must go through paths.registries_in(), which re-checks the "
            f"name case-sensitively. Inline globs found: {offenders}"
        )

# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Registry globs must not widen on a case-insensitive filesystem
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Case-insensitive-filesystem defence for every ``*_REGISTRY.json`` walk.

THE DEFECT. ``pathlib`` glob delegates matching to the filesystem, so on Windows
and default macOS ``*_REGISTRY.json`` also matches ``*_registry.json``. This repo
is full of bait — 237 lowercase files on this machine at the time of writing:
``drone_command_registry.json`` sits directly beside drone's tree, every branch
carries ``.spawn/.template_registry.json`` (pathlib ``*`` matches dotfiles, unlike
the ``glob`` module), and @flow keeps ten ``flow_json/*_registry.json`` plan
counters. Found on ef029782's windows-setup leg, root-caused by @drone.

WHY IT MATTERS HERE. My sites are identity-bearing: they answer "which project is
this" and "which registry names the caller". A command table read as a trust
anchor is the directory-name-as-identity species, back through a different door.

THE INSTRUMENT. These pins run on Linux. ``_case_insensitive_fs`` wraps
``Path.glob`` to also yield the case-folded pattern's matches — @devpulse's shape,
and a faithful emulation of what CI measured, because the bait that exists on disk
is lowercase. Its own honesty is pinned two ways: a POSITIVE control that widens a
listing *through the instrument itself* (never through a re-implementation of its
logic — that mistake cost @aipass a pin that proved nothing while visiting zero
files), and a NEGATIVE control proving the instrument can still say no.
"""

import ast
import json
from pathlib import Path

import pytest


REAL_GLOB = Path.glob


@pytest.fixture
def case_insensitive_fs(monkeypatch):
    """Make ``Path.glob`` behave as it does on Windows/macOS.

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


def _host_folds_case(directory: Path) -> bool:
    """Does THIS filesystem match a glob case-insensitively? Measured, not guessed.

    Writes ``aipass_case_probe`` and globs for the UPPERCASE spelling — the same
    direction as the defect (an uppercase pattern reaching a lowercase file), not
    a generic folding question. The first cut measured the other direction and
    came back False even under the emulator, which folds patterns downward only;
    a probe that does not travel the defect's direction reports on something
    else. A probe
    rather than ``sys.platform``, because case-folding is a property of the
    FILESYSTEM and not of the OS — macOS is folding by default and
    case-sensitive when formatted that way, and a mounted volume can disagree
    with its own host. Never skipif: a skip retires the assertion on exactly the
    platform whose CI found the defect.
    """
    marker = directory / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    try:
        return bool(list(directory.glob("AIPASS_CASE_PROBE")))
    finally:
        marker.unlink()


def test_the_host_probe_is_consistent_with_itself(tmp_path):
    """The probe's own control. It must agree with a direct existence check —
    otherwise it is reporting a property of glob rather than of the filesystem,
    and every branch it gates is chosen on noise."""
    marker = tmp_path / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    by_glob = bool(list(tmp_path.glob("AIPASS_CASE_PROBE")))
    by_stat = (tmp_path / "AIPASS_CASE_PROBE").exists()
    marker.unlink()
    assert by_glob == by_stat


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

        The claim is that the EMULATOR is what widens the listing above. On a
        case-sensitive host that reads as "the raw glob finds nothing". On
        Windows and default macOS the raw glob finds the decoy by itself — the
        host folds, which is the entire defect these pins exist for — so the
        original spelling of this control failed on the windows-setup leg of
        ebb8075d asserting `== []` against a real WindowsPath.

        So the host is PROBED, never assumed and never skipif'd (@memory's
        ruling, applied fleet-wide 2026-08-31): write ``Foo``, glob ``foo``. On a
        folding host the claim becomes the STRONGER one — the decoy is visible to
        the raw glob and ``registries_in`` refuses it anyway, which is what the
        production code has to do on the machine that actually folds. Either way
        the control can still say no; @spawn's CONTROL_LIVE probe could not until
        a mutant caught it lying.
        """
        from aipass.ai_mail.apps.handlers.paths import registries_in

        decoy = _decoy(tmp_path)

        if _host_folds_case(tmp_path):
            assert decoy in list(tmp_path.glob("*_REGISTRY.json")), (
                "host was probed as case-folding, so the raw glob must see the decoy"
            )
            assert registries_in(tmp_path) == [], (
                "on a folding host the reader is the ONLY thing standing between "
                "a counter file and the caller — and it must still refuse it"
            )
        else:
            assert list(tmp_path.glob("*_REGISTRY.json")) == []

    def test_the_probe_reports_folding_when_the_host_folds(self, tmp_path, case_insensitive_fs):
        """The Windows branch of the control above never executes on Linux, so
        it would ship unverified. Driven here through the emulator: with a
        folding glob installed the probe must SAY so, and the production reader
        must still refuse the decoy that the raw glob now hands it.

        This is the assertion that actually ran red on the windows-setup leg —
        reproduced on Linux rather than left to the next CI train to discover.
        """
        assert _host_folds_case(tmp_path) is True

        from aipass.ai_mail.apps.handlers.paths import registries_in

        decoy = _decoy(tmp_path)
        assert decoy in list(tmp_path.glob("*_REGISTRY.json"))
        assert registries_in(tmp_path) == []

    def test_the_probe_reports_case_sensitive_on_this_host(self, tmp_path):
        """Its twin, and the reason both are here: on the CI matrix these two
        tests take opposite branches, and each is the other's control."""
        assert _host_folds_case(tmp_path) is False

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
        by_name = ast.parse("d.glob(RESIDENT_REGISTRY_GLOB)").body[0].value.args[0]
        by_literal = ast.parse('d.glob("*_REGISTRY.json")').body[0].value.args[0]
        innocent = ast.parse('d.glob("*.json")').body[0].value.args[0]

        assert self._mentions_registry(by_name, module_constants) is True
        assert self._mentions_registry(by_literal, {}) is True
        assert self._mentions_registry(innocent, {}) is False

    def test_only_the_shared_reader_globs_for_registries(self):
        offenders = [o for o in self._registry_glob_calls() if o[0] != self.READER_FILE]
        assert offenders == [], (
            "registry globs must go through paths.registries_in(), which re-checks the "
            f"name case-sensitively. Inline globs found: {offenders}"
        )

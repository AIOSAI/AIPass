# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Registry globs must not widen on a case-insensitive filesystem
# Version: 1.0.3
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/paths.py's registry glob readers on a case-insensitive filesystem."""

# On Windows the pathlib glob matcher folds case, so ``*_REGISTRY.json`` also matches lowercase
# ``*_registry.json`` counter files; these sites are identity-bearing. The fixtures below emulate
# the Windows matcher and the macOS volume on Linux, with positive and negative controls.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — the real Windows/macOS case-folding behavior; emulated here, not run there

import ast
import fnmatch
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest.mock import patch

import pytest

from aipass.ai_mail.apps.handlers.paths import find_project_root, registries_in
from aipass.ai_mail.apps.handlers.users import branch_detection as bd
from aipass.ai_mail.apps.handlers.email.reply import send_reply
from aipass.ai_mail.apps.handlers.registry.read import (
    get_caller_project_branches,
    get_project_tree_branches,
    resident_registry_paths,
)


def _reply_along(tmp_path: Path, reply_path: Path):
    """send_reply to an external @vera whose message carried `reply_path`."""
    branch_a = tmp_path / "branch_a"
    branch_a.mkdir(exist_ok=True)
    original = {"id": "orig0001", "from": "@vera", "subject": "Hello", "reply_path": str(reply_path)}
    h = "aipass.ai_mail.apps.handlers"
    with (
        patch(f"{h}.users.branch_detection.get_branch_info_from_registry", return_value={"email": "@branch_a"}),
        patch(f"{h}.registry.read.get_all_branches", return_value=[]),
        patch(f"{h}.email.inbox_cleanup.mark_as_closed_and_archive", return_value=(True, "closed")),
        patch(f"{h}.email.delivery._emit_notification_event"),
    ):
        success, msg, _rid = send_reply(branch_a, original, "Reply")
    return success, msg


REAL_GLOB = Path.glob


# Volume folding and matcher folding are separate facts (macOS: volume folds, matcher does not).
# Keyed on sys.platform, not os.name: os.name collapses darwin into "posix".
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
    """Make ``Path.glob`` match the way the Windows matcher does."""

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
    """Make the VOLUME fold case, leaving the glob MATCHER as it was.

    After ``posix_matcher`` it is macOS; after ``case_insensitive_fs`` it is Windows; alone it inherits the host matcher.
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


@pytest.fixture
def posix_matcher(monkeypatch):
    """Install the posix flavour's case-sensitive wildcard matcher on ANY host.

    ``WindowsPath.glob`` folds, so a Mac world needs this on a Windows host. ``**`` is refused, not emulated.
    """

    def _glob(self, pattern, *args, **kwargs):
        if "**" in pattern:
            raise NotImplementedError("posix_matcher matches one level per component, not **")
        found = [self]
        for part in pattern.split("/"):
            found = [
                child
                for parent in found
                if parent.is_dir()
                for child in parent.iterdir()
                if fnmatch.fnmatchcase(child.name, part)
            ]
        yield from found

    monkeypatch.setattr(Path, "glob", _glob)


@pytest.fixture
def mac_world(posix_matcher, folding_volume):
    """CPython 3.13 on a default macOS volume, complete on any host: posix matcher first, folding volume over it."""


def _volume_folds_case(directory: Path) -> bool:
    """Does THIS VOLUME find a file by a name spelled in another case? Measured.

    A lookup, never a glob (3.13 answers a wildcard-free glob by lookup, 3.12 by matching). Never skipif.
    """
    marker = directory / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    try:
        return (directory / "AIPASS_CASE_PROBE").exists()
    finally:
        marker.unlink()


def _matcher_folds_case(directory: Path) -> bool:
    """Does the glob MATCHER fold case? The fact every registry walk depends on."""
    marker = directory / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    try:
        return bool(list(directory.glob("*_CASE_PROBE")))
    finally:
        marker.unlink()


def test_the_volume_probe_agrees_with_a_direct_stat(tmp_path):
    """The volume probe's own control: ``Path.exists`` and ``os.path.exists`` must agree."""
    marker = tmp_path / "aipass_case_probe"
    marker.write_text("", encoding="utf-8")
    by_stat = os.path.exists(tmp_path / "AIPASS_CASE_PROBE")
    marker.unlink()
    assert _volume_folds_case(tmp_path) is by_stat


def test_the_two_probes_ask_different_questions(tmp_path, mac_world):
    """A folding volume under a case-sensitive matcher: neither probe may stand in for the other."""
    assert _volume_folds_case(tmp_path) is True
    assert _matcher_folds_case(tmp_path) is False


def _decoy(directory: Path, name: str = "wrong_registry.json") -> Path:
    """A lowercase counter file that MAPS TO A WRONG IDENTITY.

    A well-formed ``branches`` list makes every pin about who the mail lands as, not set membership.
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
    folds = _matcher_folds_case(directory)
    decoy = _decoy(directory)

    assert (decoy in list(directory.glob("*_REGISTRY.json"))) is folds
    assert registries_in(directory) == [], "the reader refuses the counter on any filesystem"


class TestTheInstrumentIsHonest:
    """Controls: a widening emulator that never widens turns every pin below green for the wrong reason."""

    def test_positive_control_the_instrument_really_widens_a_listing(self, tmp_path, case_insensitive_fs):
        """Exercises THE INSTRUMENT, not a copy of its logic."""
        _decoy(tmp_path)
        matched = list(tmp_path.glob("*_REGISTRY.json"))
        assert [p.name for p in matched] == ["wrong_registry.json"], (
            "the instrument must make the lowercase decoy visible to an uppercase pattern"
        )

    def test_negative_control_the_instrument_can_say_no(self, tmp_path):
        """Same fixture tree, instrument NOT installed.

        The host's MATCHER is probed, never assumed and never skipif'd: on Windows the raw glob sees the decoy.
        """
        _claims_of_the_negative_control(tmp_path)

    def test_the_probe_reports_folding_when_the_host_folds(self, tmp_path, case_insensitive_fs):
        """The Windows branch of the control above, driven on Linux through the emulator."""
        assert _matcher_folds_case(tmp_path) is True

        decoy = _decoy(tmp_path)
        assert decoy in list(tmp_path.glob("*_REGISTRY.json"))
        assert registries_in(tmp_path) == []

    def test_cause_the_volume_folds_exactly_as_its_platform_row_says(self, tmp_path):
        """CAUSE, volume half. What this filesystem does, against the table."""
        expected = _expected(_VOLUME_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: volume case-folding is configurable — the matcher pins still run")
        assert _volume_folds_case(tmp_path) is expected

    def test_cause_the_matcher_folds_exactly_as_its_platform_row_says(self, tmp_path):
        """CAUSE, matcher half, the one the registry walks depend on; darwin's row follows CPython's flavour."""
        expected = _expected(_MATCHER_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: no matcher row for this platform — see the LINK pin")
        assert _matcher_folds_case(tmp_path) is expected

    def test_outcome_the_raw_glob_sees_the_decoy_exactly_when_the_matcher_row_says_so(self, tmp_path):
        """OUTCOME. Whether an uppercase pattern reaches the lowercase counter, predicted from the MATCHER row."""
        expected = _expected(_MATCHER_FOLDS_BY_PLATFORM)
        if expected is None:
            pytest.skip(f"{sys.platform}: no matcher row for this platform — see the LINK pin")
        decoy = _decoy(tmp_path)
        assert (decoy in list(tmp_path.glob("*_REGISTRY.json"))) is expected

    @pytest.mark.parametrize("platform", sorted(_MATCHER_FOLDS_BY_PLATFORM))
    def test_the_matcher_row_is_what_that_platforms_path_flavour_does(self, platform):
        """ORACLE. Both path flavours ship on every host, so each platform's matcher row runs here."""
        flavour = _MATCHER_FLAVOUR_BY_PLATFORM[platform]
        assert flavour("wrong_registry.json").match("*_REGISTRY.json") is _MATCHER_FOLDS_BY_PLATFORM[platform]

    def test_link_the_outcome_follows_from_the_cause_on_every_platform(self, tmp_path):
        """LINK. Holds with NO platform row: the glob follows the MATCHER probe, and the reader refuses either way."""
        _claims_of_the_link(tmp_path)

    def test_the_windows_row_is_driven_here_so_it_cannot_rot(self, tmp_path, case_insensitive_fs, folding_volume):
        """The win32 rows are derived, so they are driven here through both stacked emulators."""
        assert _VOLUME_FOLDS_BY_PLATFORM["win32"] is True
        assert _MATCHER_FOLDS_BY_PLATFORM["win32"] is True

        assert _volume_folds_case(tmp_path) is True, "emulated Windows must present a folding volume"
        assert _matcher_folds_case(tmp_path) is True, "emulated Windows must present a folding matcher"

        _claims_of_the_negative_control(tmp_path)
        _claims_of_the_link(tmp_path)

    def test_the_mac_row_is_driven_here_so_it_cannot_rot(self, tmp_path, mac_world):
        """The two macOS reds, reproduced on Linux: a folding volume under a case-sensitive matcher."""
        assert _MATCHER_FOLDS_BY_PLATFORM["darwin"] is False

        assert _volume_folds_case(tmp_path) is True, "emulated macOS must present a folding volume"
        assert _matcher_folds_case(tmp_path) is False, "emulated macOS must present a case-sensitive matcher"

        _claims_of_the_negative_control(tmp_path)
        _claims_of_the_link(tmp_path)

    def test_darwin_is_deliberately_unfixed_not_forgotten(self, tmp_path):
        """A None row looks like an omission, so it is pinned as a decision.

        macOS volumes are formattable either way; the matcher row is fixed False (CPython's posix flavour).
        """
        assert _VOLUME_FOLDS_BY_PLATFORM["darwin"] is None
        assert "darwin" in _VOLUME_FOLDS_BY_PLATFORM, "an absent key and a None row read the same at runtime"
        assert _MATCHER_FOLDS_BY_PLATFORM["darwin"] is False

    def test_the_fixtures_never_write_case_twins(self, tmp_path):
        """A case-twin decoy OVERWRITES on a folding filesystem, so fixtures never write twins."""
        decoy = _decoy(tmp_path)
        real = _real_registry(tmp_path)

        assert decoy.name.lower() != real.name.lower(), "fixtures would collide on a folding host"
        assert decoy.exists() and real.exists()
        assert len({decoy.name.lower(), real.name.lower()}) == 2

    def test_the_decoy_would_genuinely_seat_the_wrong_citizen(self, tmp_path):
        """The decoy is a real registry naming a real branch, so a green pin means the wrong citizen was unreachable."""
        decoy = _decoy(tmp_path)
        loaded = json.loads(decoy.read_text(encoding="utf-8"))
        assert loaded["branches"][0]["email"] == "@impostor"


class TestFindProjectRootIgnoresLowercaseCounters:
    """``paths.find_project_root`` answers 'which project is this' for the cross-project delivery fence."""

    def test_a_lowercase_counter_does_not_become_a_project_root(self, tmp_path, case_insensitive_fs):
        project = tmp_path / "project"
        _real_registry(project)
        nested = project / "branch" / "apps"
        nested.mkdir(parents=True)
        _decoy(nested.parent)  # branch/wrong_registry.json — closer than the real one

        assert find_project_root(nested) == project

    def test_the_real_registry_is_still_found(self, tmp_path, case_insensitive_fs):
        """The other half: a filter that refuses everything passes every did-not-pick-the-decoy pin."""
        project = tmp_path / "project"
        _real_registry(project)
        nested = project / "branch" / "apps"
        nested.mkdir(parents=True)

        assert find_project_root(nested) == project

    def test_an_external_project_registry_named_after_itself_survives(self, tmp_path, case_insensitive_fs):
        """SUFFIX only, never the stem: external projects name registries after themselves."""
        for stem in ("Vera-Studio", "vera_studio", "feel_good_app"):
            project = tmp_path / stem
            _real_registry(project, f"{stem}_REGISTRY.json")
            nested = project / "src" / "seat"
            nested.mkdir(parents=True)
            assert find_project_root(nested) == project, f"{stem}_REGISTRY.json must resolve"


class TestCallerRegistryNeverResolvesToACounter:
    """``branch_detection._find_caller_registry`` picks the registry that NAMES the caller.

    It returns the FIRST non-AIPass registry walking up, so a decoy ends the walk.
    """

    def test_the_impostor_registry_is_never_returned(self, tmp_path, monkeypatch, case_insensitive_fs):
        """Through get_branch_info_from_registry: the genuine seat resolves only from the real registry."""
        project = tmp_path / "project"
        _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")

        found = bd.get_branch_info_from_registry(project / "genuine")
        assert found is not None and found["email"] == "@genuine"

    def test_a_caller_identity_lookup_does_not_seat_the_impostor(self, tmp_path, monkeypatch, case_insensitive_fs):
        """The assertion that is about WHO, not about which file."""
        project = tmp_path / "project"
        _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        monkeypatch.setattr(bd, "BRANCH_REGISTRY_PATH", tmp_path / "AIPASS_REGISTRY.json")
        asked: list[str] = []
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.email.contacts.get_contact", lambda name: asked.append(name))

        # The impostor finds no registry seat and is only synthesized as external.
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "impostor")
        impostor = bd.detect_branch_from_pwd()
        assert impostor is not None and impostor["type"] == "external"
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "genuine")
        genuine = bd.detect_branch_from_pwd()
        assert genuine is not None and genuine["email"] == "@genuine"
        assert genuine.get("type") != "external"
        assert asked == ["impostor"]


class TestReplyPathValidationIsNotSatisfiedByACounter:
    """``reply._validate_reply_path`` guards delivery TOWARD an external project.

    It is existence-only, so a decoy anywhere up the chain is a full pass.
    """

    def test_a_counter_ancestor_does_not_validate_a_reply_path(self, tmp_path, case_insensitive_fs):
        stray = tmp_path / "not-a-project"
        _decoy(stray)
        inbox = stray / "seat" / ".ai_mail.local" / "inbox.json"
        inbox.parent.mkdir(parents=True)
        inbox.write_text("{}", encoding="utf-8")

        success, msg = _reply_along(tmp_path, inbox)
        assert success is False
        assert msg.startswith("Invalid reply_path: No *_REGISTRY.json found in ancestors of")

    def test_a_real_registry_ancestor_still_validates(self, tmp_path, case_insensitive_fs):
        project = tmp_path / "project"
        _real_registry(project)
        inbox = project / "seat" / ".ai_mail.local" / "inbox.json"
        inbox.parent.mkdir(parents=True)
        inbox.write_text("{}", encoding="utf-8")

        success, msg = _reply_along(tmp_path, inbox)
        assert success is True, msg
        assert [m["message"] for m in json.loads(inbox.read_text(encoding="utf-8"))["messages"]] == ["Reply"]


class TestResidentAndProjectTreeDiscovery:
    """The two sites @drone's sweep did not list: both decide WHICH CITIZENS EXIST."""

    def test_resident_discovery_skips_lowercase_counters(self, tmp_path, case_insensitive_fs):
        projects = tmp_path / "projects"
        real = _real_registry(projects / "Genuine")
        _decoy(projects / "Counterfeit")

        assert resident_registry_paths(tmp_path) == [real]

    def test_project_tree_bridge_never_admits_the_impostor(self, tmp_path, case_insensitive_fs):
        projects = tmp_path / "projects"
        _real_registry(projects / "Genuine")
        _decoy(projects / "Counterfeit")

        found = get_project_tree_branches(tmp_path)
        assert "@impostor" not in found, "the admin bridge must not gain a citizen from a counter file"
        assert "@genuine" in found

    def test_caller_project_branches_skips_the_counter(self, tmp_path, case_insensitive_fs):
        project = tmp_path / "project"
        _real_registry(project)
        caller = project / "src" / "seat"
        caller.mkdir(parents=True)
        _decoy(caller)

        found = get_caller_project_branches(str(caller))
        assert "@impostor" not in found
        assert "@genuine" in found


class TestNoInlineRegistryGlobSurvivesInTheTree:
    """The drift guard: the ban on inline registry globs is structural rather than remembered."""

    HANDLERS = Path(__file__).resolve().parents[1] / "apps"
    READER_FILE = "paths.py"

    @staticmethod
    def _mentions_registry(arg, module_constants):
        """Whether this glob argument carries a registry pattern.

        Two spellings: a literal-only ban reports ``glob(RESIDENT_REGISTRY_GLOB)`` (a Name) clean.
        """
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return "registry" in arg.value.lower()
        if isinstance(arg, ast.Name):
            return "registry" in arg.id.lower() or "registry" in str(module_constants.get(arg.id, "")).lower()
        return False

    @staticmethod
    def _sources(root):
        """Every .py under root, never inside a dropbox, .archive or __pycache__.

        Written here, not imported: seedgo's handlers guard refuses a caller from another branch.
        """
        skip = frozenset({"dropbox", ".archive", "__pycache__"})
        for source in root.rglob("*.py"):
            if not skip.intersection(source.relative_to(root).parts[:-1]):
                yield source

    def _registry_glob_calls(self, root=None):
        """Every ``.glob(...)``/``.rglob(...)`` reaching for a registry pattern, outside the one filtered reader."""
        offenders = []
        for source in self._sources(root or self.HANDLERS):
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
        """Positive control for the AST walk itself: an empty walk would pass the ban vacuously."""
        seen = [s.name for s in self._sources(self.HANDLERS)]
        assert len(seen) > 20, f"the walk must actually reach the handler tree, saw {len(seen)}"
        assert self.READER_FILE in seen

    def test_the_ban_catches_a_named_constant_not_only_a_literal(self):
        """Negative control for the RULE: a bare Name constant (resident discovery's shape) must convict."""
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

    def test_the_ban_never_reads_a_dropbox_or_an_archive(self, tmp_path):
        """A registry glob planted in a dropbox or .archive under the walked root is not read; live source is."""
        root = tmp_path / "dropbox" / "root"
        root.mkdir(parents=True)
        glob_line = 'd.glob("*_REGISTRY.json")\n'
        (root / "live.py").write_text(glob_line, encoding="utf-8")
        for skipped in ("dropbox", ".archive"):
            (root / skipped).mkdir()
            (root / skipped / "planted.py").write_text(glob_line, encoding="utf-8")

        offenders = self._registry_glob_calls(root)

        assert [name for name, _line, _arg in offenders] == ["live.py"]

    def test_only_the_shared_reader_globs_for_registries(self):
        offenders = [o for o in self._registry_glob_calls() if o[0] != self.READER_FILE]
        assert offenders == [], (
            "registry globs must go through paths.registries_in(), which re-checks the "
            f"name case-sensitively. Inline globs found: {offenders}"
        )

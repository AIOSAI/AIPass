"""Registry discovery must be case-EXACT, and no lane may glob for one again.

THE DEFECT (@devpulse relaying @drone, 2026-08-31, found on ef029782's
windows-setup leg): ``Path.glob("*_REGISTRY.json")`` matches case-INSENSITIVELY
on Windows and on default macOS, so ``*_registry.json`` matched too. Every
branch carries bait — ten ``flow_json/*_registry.json`` plan counters and
``.spawn/.template_registry.json``, which pathlib's ``*`` matches despite the
leading dot. Measured on CI, ``find_registry`` returned
``drone_command_registry.json`` as the trust-anchor candidate.

For seedgo the stakes are discovery and bypass scoping: an audit that finds
branches through a plan counter audits the wrong world, and a bypass keyed off
the wrong registry grants an exemption nobody declared.

THESE PINS RUN RED ON LINUX. The widened listing is EMULATED by wrapping the
real ``Path.glob`` so it also yields case-folded matches, and every emulated
test carries a positive control that exercises the REAL pathlib API — not a
re-implementation of the matching, which would prove only that the copy works
(@aipass's lesson, same night, from a control that visited zero files).
"""

import ast
import fnmatch
import json
import re
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers import registry_scan

REAL_ANCHOR = "AIPASS_REGISTRY.json"
COUNTER_DECOY = "flow_plan_registry.json"
DOT_DECOY = ".template_registry.json"


@pytest.fixture
def widened_glob(monkeypatch):
    """Emulate a case-insensitive filesystem's LISTING, not the caller's matching.

    Wraps pathlib's own ``Path.glob`` so a pattern also matches names that differ
    only in case — which is what Windows and default macOS do to the pattern the
    nine deleted sites passed in.
    """
    real_glob = Path.glob

    def folded_glob(self, pattern, *args, **kwargs):
        seen = {p.name: p for p in real_glob(self, pattern, *args, **kwargs)}
        matcher = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        entries = list(self.iterdir()) if self.is_dir() else []
        for entry in entries:
            if entry.name not in seen and matcher.match(entry.name):
                seen[entry.name] = entry
        for name in sorted(seen):
            yield seen[name]

    monkeypatch.setattr(Path, "glob", folded_glob)
    return folded_glob


def host_folds_glob(directory: Path) -> bool:
    """Does THIS filesystem fold case inside a glob PATTERN?

    Travels the DEFECT'S OWN DIRECTION (@ai_mail's lesson): write a lowercase
    name, glob the UPPERCASE pattern — which is exactly what the nine deleted
    sites did. Probing the other way round answers a different question and can
    answer it differently.

    DISTINCT STEMS, always (@memory's coexistence fact): two names differing
    only by case CANNOT coexist on a folding filesystem — the second write
    overwrites the FIRST'S CONTENT while the directory keeps the first's
    spelling, so a case-twin probe would be measuring a world it created.

    Args:
        directory: A writable directory; the probe gets its own subdirectory.

    Returns:
        True if the host's glob matched a name the pattern only matches when
        case is folded.
    """
    probe_dir = directory / "casefold_probe"
    probe_dir.mkdir(exist_ok=True)
    (probe_dir / "probe_registry.json").write_text("{}", encoding="utf-8")
    return [p.name for p in probe_dir.glob("*_REGISTRY.json")] != []


def _project(tmp_path):
    """A real anchor at the project root and a lowercase counter one level down.

    The decoy MAPS SOMEWHERE WRONG on purpose: a lane that returns it does not
    merely pick a different file, it discovers a different world.
    """
    root = tmp_path / "project"
    lane = root / "sub" / "flow_json"
    lane.mkdir(parents=True)
    (root / REAL_ANCHOR).write_text(
        json.dumps({"branches": {"seedgo": {"path": "src/aipass/seedgo"}}}), encoding="utf-8"
    )
    (lane / COUNTER_DECOY).write_text(
        json.dumps({"branches": {"NOT_A_BRANCH": {"path": "/nowhere"}}}), encoding="utf-8"
    )
    return root, lane


class TestTheEmulationGenuinelyWidens:
    """A positive control that fails if the instrument under test is asleep."""

    def test_pathlib_glob_finds_the_lowercase_decoy_under_emulation(self, tmp_path, widened_glob):
        _root, lane = _project(tmp_path)
        found = [p.name for p in lane.glob("*_REGISTRY.json")]
        assert COUNTER_DECOY in found, "emulation is not widening — every red below would be vacuous"

    def test_the_raw_glob_matches_the_host_it_is_running_on(self, tmp_path):
        """The negative control, PROBED rather than assumed.

        Its first spelling asserted the raw glob finds nothing — true on this
        Linux runner and FALSE on real Windows, where NTFS folds and the decoy
        comes straight back. A control that fails on the exact host the defect
        lives on is worse than none: it turns the CI leg that found the bug red
        for the instrument's own reason. Both outcomes are pinned; nothing is
        skipped (@memory's ruling: never skipif what a probe can measure).
        """
        _root, lane = _project(tmp_path)
        found = [p.name for p in lane.glob("*_REGISTRY.json")]
        if host_folds_glob(tmp_path):
            assert COUNTER_DECOY in found, "host folds case but the raw glob missed the decoy"
        else:
            assert found == [], "host is case-sensitive but the raw glob matched anyway"

    def test_the_probe_answers_from_the_filesystem_not_from_sys_platform(self, tmp_path, widened_glob):
        """Probe integrity (@aipass's trick), and it is killable HERE.

        Under the emulation this Linux runner behaves like a folding host, so a
        probe that read ``sys.platform`` would still answer False and this line
        goes red. The opposite mutant — a probe hardwired to True — dies in the
        test above, which on this case-sensitive host demands an empty listing.
        Both directions have a killer on whichever host is running.
        """
        assert host_folds_glob(tmp_path) is True


class TestDiscoveryPointsAtTheRealAnchorOnACaseFoldingFilesystem:
    def test_the_upward_walk_skips_the_counter_and_keeps_climbing(self, tmp_path, widened_glob):
        root, lane = _project(tmp_path)
        found = registry_scan.find_registry_upward(lane)
        assert found == root / REAL_ANCHOR

    def test_what_it_finds_maps_the_real_world(self, tmp_path, widened_glob):
        """The assertion is about where discovery POINTS, not set membership."""
        _root, lane = _project(tmp_path)
        found = registry_scan.find_registry_upward(lane)
        assert found is not None
        assert "seedgo" in json.loads(found.read_text(encoding="utf-8"))["branches"]

    def test_the_directory_listing_excludes_the_counter(self, tmp_path, widened_glob):
        _root, lane = _project(tmp_path)
        assert registry_scan.registries_in(lane) == []

    def test_caller_registries_skips_the_counter_too(self, tmp_path, widened_glob, monkeypatch):
        root, lane = _project(tmp_path)
        monkeypatch.setenv(registry_scan.CALLER_CWD_VAR, str(lane))
        assert registry_scan.caller_registries() == [root / REAL_ANCHOR]


class TestTheNameCheckIsCaseExactWithoutAnyEmulation:
    """These need no filesystem trick: a checker that folds case fails them on Linux."""

    def test_a_lowercase_counter_is_not_a_registry(self, tmp_path):
        (tmp_path / COUNTER_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == []

    def test_a_dotted_counter_is_not_a_registry(self, tmp_path):
        """pathlib's ``*`` matches dotfiles where the glob module does not."""
        (tmp_path / DOT_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == []

    def test_an_external_projects_own_registry_survives(self, tmp_path):
        """SUFFIX only, never the stem: nothing promises an uppercase stem, and
        Vera-Studio_REGISTRY.json is a real one in the live fleet."""
        target = tmp_path / "Vera-Studio_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == [target]

    def test_a_lowercase_stem_still_survives(self, tmp_path):
        target = tmp_path / "vera-studio_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")
        assert registry_scan.registries_in(tmp_path) == [target]

    def test_a_directory_wearing_the_name_is_not_a_registry(self, tmp_path):
        (tmp_path / f"folder{registry_scan.REGISTRY_SUFFIX}").mkdir()
        assert registry_scan.registries_in(tmp_path) == []

    def test_a_missing_directory_answers_empty_rather_than_raising(self, tmp_path):
        assert registry_scan.registries_in(tmp_path / "absent") == []

    def test_the_walk_answers_None_when_nothing_is_above(self, tmp_path):
        (tmp_path / COUNTER_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.find_registry_upward(tmp_path) is None


class TestEveryLaneReadsTheSharedReader:
    """The four private walks are gone; each name now delegates.

    Patched on the MODULE so the assertion proves a call-time lookup — a lane
    that had done ``from ... import find_registry`` would keep its own binding
    and these would pass while reading something else.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "aipass.seedgo.apps.handlers.audit.discovery",
            "aipass.seedgo.apps.handlers.bypass.bypass_handler",
            "aipass.seedgo.apps.handlers.diagnostics.discovery",
            "aipass.seedgo.apps.handlers.readme.readme_ops",
        ],
    )
    def test_the_lane_returns_what_the_shared_reader_returns(self, module_path, monkeypatch, tmp_path):
        import importlib

        module = importlib.import_module(module_path)
        sentinel = tmp_path / "SENTINEL_REGISTRY.json"
        monkeypatch.setattr(registry_scan, "find_registry", lambda: sentinel)
        assert module._find_registry() == sentinel

    def test_the_caller_lane_delegates_too(self, monkeypatch, tmp_path):
        from aipass.seedgo.apps.handlers.audit import discovery

        sentinel = [tmp_path / "SENTINEL_REGISTRY.json"]
        monkeypatch.setattr(registry_scan, "caller_registries", lambda: sentinel)
        assert discovery._find_caller_registries() == sentinel


class TestNoLaneGlobsForARegistryAnyMore:
    """A parse-tree sweep, so the tenth walk cannot be written quietly.

    Named offenders, not a count: a sweep that reports a number tells the next
    reader nothing about where to look.
    """

    def _glob_call_sites(self, tree, path):
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("glob", "rglob"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if any(char.isupper() for char in Path(arg.value).name):
                        offenders.append(f"{path}:{node.lineno} {arg.value}")
        return offenders

    def test_no_cased_glob_pattern_survives_in_the_source_tree(self):
        source_root = Path(__file__).resolve().parents[1] / "apps"
        offenders = []
        for py_file in sorted(source_root.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            offenders.extend(self._glob_call_sites(tree, py_file.relative_to(source_root)))
        assert offenders == [], f"cased glob patterns fold on Windows: {offenders}"

    def test_the_sweep_can_see_an_offender(self):
        """Positive control on the INSTRUMENT: the same walker, on a real file
        holding the deleted spelling — not a re-implementation of the match."""
        tree = ast.parse('from pathlib import Path\nx = Path(".").glob("*_REGISTRY.json")\n')
        assert self._glob_call_sites(tree, Path("probe.py")) != []

    def test_the_sweep_leaves_lowercase_patterns_alone(self):
        tree = ast.parse('from pathlib import Path\nx = Path(".").rglob("*.py")\n')
        assert self._glob_call_sites(tree, Path("probe.py")) == []

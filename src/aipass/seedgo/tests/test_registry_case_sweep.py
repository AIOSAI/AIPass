# =================== META ====================
# Name: test_registry_case_sweep.py
# Description: Case-exact registry discovery, and the sweep that keeps every lane off the glob
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/registry_scan.py and the lanes that delegate to it."""

# Registry discovery is case-exact: Path.glob matches case-insensitively on Windows and macOS, so *_REGISTRY.json
# also finds plan counters. The widened listing is emulated by a Path subclass; each emulated test has a real-pathlib control.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/registry_scan.py and the four delegating lanes parse and import
# seedgo: no-test-needed(constant) — DEFAULT_REGISTRY_NAME's text, the name find_registry falls back to
# seedgo: no-test-needed(stdlib) — os.environ.get's lookup; the tests only choose what AIPASS_CALLER_CWD holds

import ast
import fnmatch
import json
import re
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.audit import discovery

REAL_ANCHOR = "AIPASS_REGISTRY.json"
COUNTER_DECOY = "flow_plan_registry.json"
DOT_DECOY = ".template_registry.json"


class _FoldingPath(type(Path())):
    """A path whose ``glob`` also yields names that differ only in case, as a folding host lists them."""

    def glob(self, pattern, *args, **kwargs):
        seen = {p.name: p for p in super().glob(pattern, *args, **kwargs)}
        matcher = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        entries = list(self.iterdir()) if self.is_dir() else []
        for entry in entries:
            if entry.name not in seen and matcher.match(entry.name):
                seen[entry.name] = entry
        for name in sorted(seen):
            yield seen[name]


@pytest.fixture
def widened_glob(monkeypatch):
    """Emulate a case-insensitive filesystem's LISTING, not the caller's matching."""
    monkeypatch.setattr(registry_scan, "Path", _FoldingPath)
    return _FoldingPath


def host_folds_glob(directory: Path) -> bool:
    """Does THIS filesystem fold case inside a glob PATTERN?"""
    probe_dir = directory / "casefold_probe"
    probe_dir.mkdir(exist_ok=True)
    (probe_dir / "probe_registry.json").write_text("{}", encoding="utf-8")
    return [p.name for p in probe_dir.glob("*_REGISTRY.json")] != []


def _project(tmp_path):
    """A real anchor at the project root and a lowercase counter one level down."""
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
        found = [p.name for p in widened_glob(lane).glob("*_REGISTRY.json")]
        assert COUNTER_DECOY in found, "emulation is not widening — every red below would be vacuous"

    def test_the_raw_glob_matches_the_host_it_is_running_on(self, tmp_path):
        """The negative control, PROBED rather than assumed."""
        _root, lane = _project(tmp_path)
        found = [p.name for p in lane.glob("*_REGISTRY.json")]
        if host_folds_glob(tmp_path):
            assert COUNTER_DECOY in found, "host folds case but the raw glob missed the decoy"
        else:
            assert found == [], "host is case-sensitive but the raw glob matched anyway"

    def test_the_probe_answers_from_the_filesystem_not_from_sys_platform(self, tmp_path, widened_glob):
        """Probe integrity (@aipass's trick), and it is killable HERE."""
        assert host_folds_glob(widened_glob(tmp_path)) is True


class TestDiscoveryPointsAtTheRealAnchorOnACaseFoldingFilesystem:
    def test_the_upward_walk_skips_the_counter_and_keeps_climbing(self, tmp_path, widened_glob):
        root, lane = _project(tmp_path)
        found = registry_scan.find_registry_upward(widened_glob(lane))
        assert found == root / REAL_ANCHOR

    def test_what_it_finds_maps_the_real_world(self, tmp_path, widened_glob):
        """The assertion is about where discovery POINTS, not set membership."""
        _root, lane = _project(tmp_path)
        found = registry_scan.find_registry_upward(widened_glob(lane))
        assert found is not None
        assert json.loads(found.read_text(encoding="utf-8"))["branches"] == {"seedgo": {"path": "src/aipass/seedgo"}}

    def test_the_directory_listing_excludes_the_counter(self, tmp_path, widened_glob):
        _root, lane = _project(tmp_path)
        assert registry_scan.registries_in(widened_glob(lane)) == []

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
        """The suffix is matched case-exact, never the stem: Vera-Studio_REGISTRY.json is a real registry."""
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

    def test_the_walk_answers_none_when_nothing_is_above(self, tmp_path):
        (tmp_path / COUNTER_DECOY).write_text("{}", encoding="utf-8")
        assert registry_scan.find_registry_upward(tmp_path) is None


class TestEveryLaneReadsTheSharedReader:
    """The four private walks are gone; each name now delegates."""

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
        """Mutant: _find_caller_registries answers [] in apps/handlers/audit/discovery.py — killed."""
        caller = tmp_path / "caller"
        (caller / "callerbranch" / "apps").mkdir(parents=True)
        (caller / "callerbranch" / "apps" / "callerbranch.py").write_text("", encoding="utf-8")
        sentinel = caller / "SENTINEL_REGISTRY.json"
        sentinel.write_text(
            json.dumps({"branches": [{"name": "callerbranch", "path": "callerbranch"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(registry_scan, "find_registry", lambda: tmp_path / "absent" / REAL_ANCHOR)
        monkeypatch.setattr(registry_scan, "caller_registries", lambda: [sentinel])
        found = discovery.discover_branches(include_private=True)
        assert [b["name"] for b in found] == ["callerbranch"]


class TestNoLaneGlobsForARegistryAnyMore:
    """A parse-tree sweep, so the tenth walk cannot be written quietly."""

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
        """Positive control on the instrument: the same walker finds the deleted spelling in a real file."""
        tree = ast.parse('from pathlib import Path\nx = Path(".").glob("*_REGISTRY.json")\n')
        assert self._glob_call_sites(tree, Path("probe.py")) != []

    def test_the_sweep_leaves_lowercase_patterns_alone(self):
        tree = ast.parse('from pathlib import Path\nx = Path(".").rglob("*.py")\n')
        assert self._glob_call_sites(tree, Path("probe.py")) == []

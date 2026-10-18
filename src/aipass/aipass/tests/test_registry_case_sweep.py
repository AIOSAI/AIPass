# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Case-insensitive filesystem pins for *_REGISTRY.json discovery
# Version: 1.2.2
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for shared/registry_discovery.py and its case-insensitive-filesystem pins."""
# Every *_REGISTRY.json walk must be case-SENSITIVE: Path.glob folds case on Windows/macOS
# and reaches *_registry.json plan counters. The pins run red on Linux by emulating that.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the registry-discovery module and the modules it imports parse and import

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

import pytest

from aipass.aipass.shared.registry_discovery import find_registry, registries_in

BRANCH_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def case_insensitive_fs(monkeypatch: pytest.MonkeyPatch):
    """Make ``Path.glob`` behave the way Windows/macOS behave.

    Valid only for single-component, non-recursive patterns: every registry walk here.
    """
    real_iterdir = Path.iterdir

    def widened(self: Path, pattern: str, *args, **kwargs):
        rx = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        if not self.is_dir():
            return iter(())  # the real glob of a missing directory is empty too
        return iter(sorted(p for p in real_iterdir(self) if rx.match(p.name)))

    monkeypatch.setattr(Path, "glob", widened)
    return widened


def host_folds_case(tmp_path: Path) -> bool:
    """Does THIS filesystem fold case? Asked in the DEFECT'S OWN DIRECTION.

    Lowercase file, uppercase pattern; a probe, never a skipif, so both answers are pinned.
    """
    probe = tmp_path / "_case_probe"
    probe.mkdir(exist_ok=True)
    (probe / "probe_registry.json").write_text("{}", encoding="utf-8")
    return [path.name for path in probe.glob("*_REGISTRY.json")] == ["probe_registry.json"]


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """A project root with the real anchor, and a DECOY one level down.

    Met before the root, so widening changes the answer; distinct stems, as case twins cannot coexist.
    """
    root = tmp_path / "root"
    deep = root / "sub" / "deep"
    deep.mkdir(parents=True)
    (root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    (root / "sub" / "flow_registry.json").write_text("{}", encoding="utf-8")
    (root / "sub" / ".template_registry.json").write_text("{}", encoding="utf-8")
    return root, deep


DECOY_NAMES = {"flow_registry.json", ".template_registry.json"}


class TestTheEmulationIsNotBlind:
    """A blinded fixture reports green identically to a cure.  Prove it bites."""

    def test_the_raw_glob_answers_exactly_as_the_host_folds(self, tmp_path: Path) -> None:
        """The control, pinned in BOTH worlds rather than assuming one.

        Where the host folds, the raw glob reaches the decoys; elsewhere only the emulation widens.
        """
        root, _ = _project(tmp_path)
        found = {path.name for path in (root / "sub").glob("*_REGISTRY.json")}
        if host_folds_case(tmp_path):
            assert found == DECOY_NAMES, (
                f"host folds case, so the raw glob must reach the lowercase decoys -- got {found}"
            )
        else:
            assert found == set(), f"host does NOT fold case, so the raw glob must reach nothing -- got {found}"

    def test_with_emulation_the_lowercase_decoy_is_matched(self, tmp_path: Path, case_insensitive_fs) -> None:
        """If this goes green-by-accident the whole file proves nothing."""
        root, _ = _project(tmp_path)
        names = {p.name for p in (root / "sub").glob("*_REGISTRY.json")}
        assert names == DECOY_NAMES, f"emulation did not widen -- these pins would pass blind: {names}"

    def test_the_probe_reads_the_world_not_a_platform_string(self, tmp_path: Path, case_insensitive_fs) -> None:
        """The probe must be an experiment, not ``sys.platform`` in disguise.

        Inside the emulation a platform string says False on Linux; a real glob says True.
        """
        assert host_folds_case(tmp_path) is True, (
            "the probe did not see a folding world it was standing in -- it is not measuring the filesystem"
        )


class TestRegistriesIn:
    def test_rejects_lowercase_even_on_a_case_insensitive_filesystem(self, tmp_path: Path, case_insensitive_fs) -> None:
        root, _ = _project(tmp_path)
        assert registries_in(root / "sub") == []

    def test_still_finds_the_real_anchor(self, tmp_path: Path, case_insensitive_fs) -> None:
        root, _ = _project(tmp_path)
        assert [p.name for p in registries_in(root)] == ["AIPASS_REGISTRY.json"]

    def test_suffix_not_stem_external_projects_name_registries_after_themselves(
        self, tmp_path: Path, case_insensitive_fs
    ) -> None:
        """``VERA-STUDIO_REGISTRY.json`` is valid; nothing promises an uppercase stem."""
        tmp_path.joinpath("Vera-Studio_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert [p.name for p in registries_in(tmp_path)] == ["Vera-Studio_REGISTRY.json"]

    def test_unreadable_directory_is_empty_not_an_exception(self, tmp_path: Path) -> None:
        assert registries_in(tmp_path / "does_not_exist") == []


class TestFindRegistryUnderCaseInsensitivity:
    def test_the_decoy_does_not_become_the_trust_anchor(self, tmp_path: Path, case_insensitive_fs) -> None:
        """The assertion is WHERE discovery points, not what a list contains."""
        root, deep = _project(tmp_path)
        found = find_registry(start_path=deep)
        assert found is not None
        assert found == root / "AIPASS_REGISTRY.json"
        assert found.parent == root, f"project root resolved to {found.parent}, not {root}"

    def test_a_directory_holding_only_counters_is_registry_free(self, tmp_path: Path, case_insensitive_fs) -> None:
        """No anchor anywhere -- absence, not a counter dressed as an anchor."""
        only = tmp_path / "counters"
        only.mkdir()
        (only / "fplan_registry.json").write_text("{}", encoding="utf-8")
        (only / ".template_registry.json").write_text("{}", encoding="utf-8")
        assert find_registry(start_path=only, package_root=str(only)) is None

    def test_package_root_walk_is_filtered_too(self, tmp_path: Path, case_insensitive_fs) -> None:
        """Priority 3 is a second walk -- it needs the same filter as priority 2."""
        root, deep = _project(tmp_path)
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        assert find_registry(start_path=isolated, package_root=str(deep)) == (root / "AIPASS_REGISTRY.json")


def _private_registry_globs(root: Path) -> tuple[list[str], int]:
    """Every direct ``glob("*_REGISTRY.json")`` under *root*, and the file count."""
    offenders: list[str] = []
    scanned = 0
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if {"dropbox", ".archive", ".backup", "__pycache__", "docs.local"} & set(py.relative_to(root).parts):
            continue
        if rel in {"tests/test_registry_case_sweep.py", "shared/registry_discovery.py"}:
            continue  # the pin itself, and the one sanctioned implementation
        # A live file that will not parse raises here: skipping it could hide a glob.
        tree = ast.parse(py.read_text(encoding="utf-8"))
        scanned += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"glob", "rglob"}:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.endswith("_REGISTRY.json")
                ):
                    offenders.append(f"{rel}:{node.lineno}")
    return offenders, scanned


class TestNoPrivateRegistryGlobSurvives:
    """One reader, called by every walk."""

    def test_no_module_globs_the_registry_pattern_directly(self) -> None:
        offenders, scanned = _private_registry_globs(BRANCH_ROOT)
        assert offenders == [], "private *_REGISTRY.json glob(s) -- call shared registries_in() instead: " + ", ".join(
            offenders
        )

    def test_the_walk_actually_walked(self) -> None:
        """A scan that visits nothing reports clean.  Refuse to call that a pass.

        A mutant blinding the skip-list visited zero files and every assertion still passed.
        """
        _, scanned = _private_registry_globs(BRANCH_ROOT)
        assert scanned > 50, f"walk only parsed {scanned} modules -- it is blind, not clean"

    def test_the_same_walk_convicts_a_planted_offender(self, tmp_path: Path) -> None:
        """Positive control through the REAL function, not a re-implementation."""
        (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "guilty.py").write_text(
            'from pathlib import Path\nx = Path(".").glob("*_REGISTRY.json")\n',
            encoding="utf-8",
        )
        offenders, scanned = _private_registry_globs(tmp_path)
        assert offenders == ["guilty.py:2"]
        assert scanned == 2

    def test_the_walk_never_enters_a_sandbox_or_scratch(self, tmp_path: Path) -> None:
        """A glob planted in each skipped directory goes unread; the live one beside them is convicted."""
        planted = 'from pathlib import Path\nx = Path(".").glob("*_REGISTRY.json")\n'
        for skipped in ("dropbox", ".archive", "__pycache__", "docs.local"):
            (tmp_path / skipped).mkdir()
            (tmp_path / skipped / "planted.py").write_text(planted, encoding="utf-8")
        (tmp_path / "live.py").write_text(planted, encoding="utf-8")
        assert _private_registry_globs(tmp_path) == (["live.py:2"], 1)

    def test_the_walk_also_catches_rglob(self, tmp_path: Path) -> None:
        """``rglob`` is the same defect one keystroke away."""
        (tmp_path / "guilty.py").write_text(
            'from pathlib import Path\nx = Path(".").rglob("*_REGISTRY.json")\n',
            encoding="utf-8",
        )
        offenders, _ = _private_registry_globs(tmp_path)
        assert offenders == ["guilty.py:2"]

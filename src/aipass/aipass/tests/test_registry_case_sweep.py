# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: Pins for *_REGISTRY.json discovery
# Version: 1.2.2
# Created: 2026-08-31
# Modified: 2026-11-02
# =============================================

"""Tests for shared/registry_discovery.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the registry-discovery module and the modules it imports parse and import

from __future__ import annotations

import ast
from pathlib import Path

from aipass.aipass.shared.registry_discovery import registries_in

BRANCH_ROOT = Path(__file__).resolve().parents[1]


class TestRegistriesIn:
    def test_suffix_not_stem_external_projects_name_registries_after_themselves(self, tmp_path: Path) -> None:
        """``VERA-STUDIO_REGISTRY.json`` is valid; nothing promises an uppercase stem."""
        tmp_path.joinpath("Vera-Studio_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert [p.name for p in registries_in(tmp_path)] == ["Vera-Studio_REGISTRY.json"]

    def test_unreadable_directory_is_empty_not_an_exception(self, tmp_path: Path) -> None:
        assert registries_in(tmp_path / "does_not_exist") == []


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

"""Canaries for what the shipped templates are allowed to contain.

A template is a blueprint: every file in it is copied into every new citizen,
forever. Build artifacts that drift in are invisible — they cost nothing to
create and never fail anything — so they need a standing test rather than a
review pass.

`.pytest_cache/` drifted in this way (flagged 2026-08-07, still shipping on
2026-08-13): the copy engine skips `__pycache__` but not `.pytest_cache`, so
every branch was born carrying spawn's own cached test node IDs
(DPLAN-0291 audit).
"""

from pathlib import Path

import pytest

import aipass.spawn
from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir

ARTIFACT_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}

# __pycache__ reappears in the template tree whenever anything imports its .py files.
# It is gitignored and never copied, so its presence on disk proves nothing — the tree
# canaries below check only the artifacts that persist and get committed.
TRANSIENT_DIRS = {"__pycache__"}
PERSISTENT_ARTIFACTS = ARTIFACT_DIRS - TRANSIENT_DIRS

TEMPLATE_CLASSES = sorted(get_available_classes())


def _template_registry(class_name: str) -> Path:
    return get_template_dir(class_name) / ".spawn" / ".template_registry.json"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_no_build_artifacts_in_template_tree(class_name):
    """No cache directory may live in a template — it would be copied into every branch."""
    template = get_template_dir(class_name)

    found = [
        str(path.relative_to(template))
        for path in template.rglob("*")
        if path.is_dir() and path.name in PERSISTENT_ARTIFACTS
    ]

    assert found == [], f"{class_name} template ships build artifacts: {found}"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_no_build_artifacts_tracked_in_registry(class_name):
    """The registry must not track artifacts either — tracking re-adds them on update."""
    import json

    registry_path = _template_registry(class_name)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    tracked = list(registry.get("files", {}).values()) + list(registry.get("directories", {}).values())
    paths = [entry if isinstance(entry, str) else entry.get("path", "") for entry in tracked]

    polluted = [p for p in paths if any(part in ARTIFACT_DIRS for part in Path(p).parts)]

    assert polluted == [], f"{class_name} registry tracks build artifacts: {polluted}"


def test_copy_engine_skips_artifact_dirs():
    """The skip set is the enforcement point — keep it honest about every cache dir."""
    from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES

    assert ARTIFACT_DIRS <= set(SKIP_NAMES)


def test_spawn_package_ships_no_artifact_dirs():
    """Belt and braces: the installed package itself carries no cache dirs under templates/."""
    templates_root = Path(aipass.spawn.__file__).parent / "templates"

    found = [str(p) for p in templates_root.rglob("*") if p.is_dir() and p.name in PERSISTENT_ARTIFACTS]

    assert found == []

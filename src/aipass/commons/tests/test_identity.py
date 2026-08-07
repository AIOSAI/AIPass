# =================== AIPass ====================
# Name: test_identity.py
# Description: Unit tests for identity module and identity_ops handler
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-06-15
# =============================================

"""
Unit tests for the commons identity module and identity_ops handler.

Tests extract_mentions (pure regex), find_branch_root (filesystem walk),
resolve_display_name, and DB-backed mention validation.
"""

import logging
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

logger = logging.getLogger(__name__)

_mock_logger = MagicMock()
_mock_logger_module = MagicMock()
_mock_logger_module.system_logger = _mock_logger

try:
    from aipass.prax.apps.modules.logger import system_logger  # noqa: F401
except ImportError:
    logger.warning("[test_identity] prax unavailable — injecting mock logger")
    sys.modules.setdefault("aipass.prax", MagicMock())
    sys.modules.setdefault("aipass.prax.apps", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules.logger", _mock_logger_module)

try:
    from aipass.cli.apps.modules import console  # noqa: F401
except ImportError:
    logger.warning("[test_identity] cli unavailable — injecting mock console")
    _mock_cli = MagicMock()
    sys.modules.setdefault("aipass.cli", _mock_cli)
    sys.modules.setdefault("aipass.cli.apps", MagicMock())
    sys.modules.setdefault("aipass.cli.apps.modules", MagicMock())

from aipass.commons.apps.modules import commons_identity as _id_mod  # noqa: E402
from aipass.commons.apps.handlers.identity import identity_ops as _ops  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_db_for_mentions(initialized_db: sqlite3.Connection):
    """
    Patch get_db/close_db in the database module so that
    extract_mentions (which does a lazy import) uses the test database.
    """
    with (
        patch(
            "aipass.commons.apps.handlers.database.db.get_db",
            return_value=initialized_db,
        ),
        patch(
            "aipass.commons.apps.handlers.database.db.close_db",
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _isolate_caller_env(monkeypatch: pytest.MonkeyPatch):
    """
    Keep ambient drone env vars out of registry resolution.

    Registry lookup now walks up from AIPASS_CALLER_CWD, so a value
    inherited from the shell running pytest would let a real registry
    answer a lookup a test meant to miss. Tests that exercise the walk
    set the var themselves.
    """
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)


def _write_registry(path: Path, branches) -> Path:
    """Write a registry file with the given branches payload."""
    import json as json_mod

    path.write_text(json_mod.dumps({"branches": branches}), encoding="utf-8")
    return path


def _make_external_project(root: Path, name: str = "VERA", email: str = "@vera") -> Path:
    """
    Build a minimal external project: a named registry plus a passported branch.

    Mirrors the real shape of an external citizen's project — registry at
    the project root named after the project, branch paths relative to it,
    each branch a real directory carrying .trinity/passport.json.
    """
    branch_dir = root / "src" / "vera_studio" / name.lower()
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")

    _write_registry(
        root / "VERA-STUDIO_REGISTRY.json",
        [{"name": name, "path": f"src/vera_studio/{name.lower()}", "email": email, "description": "CEO"}],
    )
    return branch_dir


# ===========================================================================
# extract_mentions — regex extraction + DB validation
# ===========================================================================


def test_extract_mentions_empty_string(initialized_db: sqlite3.Connection):
    """Empty string returns empty list."""
    result = _id_mod.extract_mentions("")
    assert result == []


def test_extract_mentions_no_mentions(initialized_db: sqlite3.Connection):
    """Text without @mentions returns empty list."""
    result = _id_mod.extract_mentions("Hello world, no mentions here")
    assert result == []


def test_extract_mentions_single(initialized_db: sqlite3.Connection):
    """Single @mention of a registered agent is returned."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("drone", "Drone"),
    )
    initialized_db.commit()

    result = _id_mod.extract_mentions("Hey @drone check this out")
    assert result == ["drone"]


def test_extract_mentions_multiple(initialized_db: sqlite3.Connection):
    """Multiple @mentions of registered agents are all returned."""
    for name, display in [("flow", "Flow"), ("seed", "Seed")]:
        initialized_db.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
            (name, display),
        )
    initialized_db.commit()

    result = _id_mod.extract_mentions("@flow and @seed please review")
    assert result == ["flow", "seed"]


def test_extract_mentions_unregistered_filtered(initialized_db: sqlite3.Connection):
    """Mentions of agents not in the DB are filtered out."""
    result = _id_mod.extract_mentions("@nonexistent_branch please help")
    assert result == []


def test_extract_mentions_case_insensitive(initialized_db: sqlite3.Connection):
    """Mentions are lowercased for DB lookup."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("prax", "Prax"),
    )
    initialized_db.commit()

    result = _id_mod.extract_mentions("Hey @PRAX look at this")
    assert result == ["prax"]


def test_extract_mentions_with_underscores(initialized_db: sqlite3.Connection):
    """Mentions with underscores (e.g., @ai_mail) are matched."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("ai_mail", "AI Mail"),
    )
    initialized_db.commit()

    result = _id_mod.extract_mentions("Asking @ai_mail for analysis")
    assert result == ["ai_mail"]


# ===========================================================================
# find_branch_root — filesystem walk
# ===========================================================================


def test_find_branch_root_with_trinity(tmp_path: Path):
    """Finds root when .trinity/passport.json exists."""
    trinity_dir = tmp_path / ".trinity"
    trinity_dir.mkdir()
    (trinity_dir / "passport.json").write_text("{}", encoding="utf-8")

    sub = tmp_path / "apps" / "handlers"
    sub.mkdir(parents=True)

    result = _id_mod.find_branch_root(sub)
    assert result is not None
    assert result == tmp_path.resolve()


def test_find_branch_root_no_trinity(tmp_path: Path):
    """Returns None when no .trinity directory exists in ancestry."""
    sub = tmp_path / "deep" / "nested" / "dir"
    sub.mkdir(parents=True)

    result = _id_mod.find_branch_root(sub)
    assert result is None


def test_find_branch_root_at_start(tmp_path: Path):
    """Finds root when start_path IS the branch root."""
    trinity_dir = tmp_path / ".trinity"
    trinity_dir.mkdir()
    (trinity_dir / "passport.json").write_text("{}", encoding="utf-8")

    result = _id_mod.find_branch_root(tmp_path)
    assert result is not None
    assert result == tmp_path.resolve()


# ===========================================================================
# resolve_display_name
# ===========================================================================


def test_resolve_display_name_no_alias(monkeypatch: pytest.MonkeyPatch):
    """Falls back to branch_name when no alias is cached."""
    monkeypatch.setattr("aipass.commons.apps.handlers.identity.identity_ops._alias_cache", {})
    result = _id_mod.resolve_display_name("UNKNOWN_BRANCH")
    assert result == "UNKNOWN_BRANCH"


def test_resolve_display_name_with_alias(monkeypatch: pytest.MonkeyPatch):
    """Returns 'Alias (SYSTEM_NAME)' format when alias exists."""
    monkeypatch.setattr("aipass.commons.apps.handlers.identity.identity_ops._alias_cache", {"TEAM_1": "Alpha Team"})
    result = _id_mod.resolve_display_name("TEAM_1")
    assert result == "Alpha Team (TEAM_1)"


def test_resolve_display_name_compact(monkeypatch: pytest.MonkeyPatch):
    """Compact mode returns alias only, no parenthesized system name."""
    monkeypatch.setattr("aipass.commons.apps.handlers.identity.identity_ops._alias_cache", {"TEAM_1": "Alpha Team"})
    result = _id_mod.resolve_display_name("TEAM_1", compact=True)
    assert result == "Alpha Team"


def test_resolve_display_name_compact_no_alias(monkeypatch: pytest.MonkeyPatch):
    """Compact mode without alias still falls back to branch_name."""
    monkeypatch.setattr("aipass.commons.apps.handlers.identity.identity_ops._alias_cache", {})
    result = _id_mod.resolve_display_name("RAW_NAME", compact=True)
    assert result == "RAW_NAME"


# ===========================================================================
# get_branch_info_by_name — registry lookup by name
# ===========================================================================


def test_get_branch_info_by_name_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns branch info when name matches a registry entry."""
    import json as json_mod

    registry = {
        "branches": [
            {"name": "DRONE", "path": "src/aipass/drone", "email": "@drone"},
            {"name": "FLOW", "path": "src/aipass/flow", "email": "@flow"},
        ]
    }
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json_mod.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        reg_file,
    )

    result = _id_mod.get_branch_info_by_name("drone")
    assert result is not None
    assert result["name"] == "DRONE"
    assert result["email"] == "@drone"


def test_get_branch_info_by_name_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Lookup is case-insensitive."""
    import json as json_mod

    registry = {"branches": [{"name": "FLOW", "path": "src/aipass/flow"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json_mod.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        reg_file,
    )

    result = _id_mod.get_branch_info_by_name("Flow")
    assert result is not None
    assert result["name"] == "FLOW"


def test_get_branch_info_by_name_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns None when name is not in registry."""
    import json as json_mod

    registry = {"branches": [{"name": "DRONE", "path": "src/aipass/drone"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json_mod.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        reg_file,
    )

    result = _id_mod.get_branch_info_by_name("nonexistent")
    assert result is None


def test_get_branch_info_by_name_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Returns None when registry file doesn't exist."""
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        tmp_path / "nope.json",
    )
    result = _id_mod.get_branch_info_by_name("DRONE")
    assert result is None


# ===========================================================================
# get_caller_branch — drone routing fallback via AIPASS_CALLER_BRANCH
# ===========================================================================


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler")
@patch("aipass.commons.apps.handlers.identity.identity_ops._ensure_agent_registered")
def test_get_caller_branch_uses_caller_branch_env(
    mock_register: MagicMock,
    mock_json: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Falls back to AIPASS_CALLER_BRANCH when CWD has no .trinity/."""
    import json as json_mod

    registry = {"branches": [{"name": "DRONE", "path": "src/aipass/drone", "email": "@drone"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json_mod.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        reg_file,
    )

    no_branch_dir = tmp_path / "somewhere"
    no_branch_dir.mkdir()
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(no_branch_dir))
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "drone")

    result = _id_mod.get_caller_branch()
    assert result is not None
    assert result["name"] == "drone"
    mock_register.assert_called_once()


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler")
@patch("aipass.commons.apps.handlers.identity.identity_ops._ensure_agent_registered")
def test_get_caller_branch_prefers_cwd_over_env(
    mock_register: MagicMock,
    mock_json: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """CWD-based detection takes priority over AIPASS_CALLER_BRANCH."""
    import json as json_mod

    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    (trinity / "passport.json").write_text("{}", encoding="utf-8")

    registry = {
        "branches": [
            {
                "name": "FLOW",
                "path": str(tmp_path.relative_to(tmp_path.parent.parent)),
                "email": "@flow",
            },
        ]
    }
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json_mod.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH",
        reg_file,
    )

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "DRONE")

    with patch(
        "aipass.commons.apps.handlers.identity.identity_ops.get_branch_info_from_registry",
        return_value={"name": "FLOW", "email": "@flow"},
    ):
        result = _id_mod.get_caller_branch()

    assert result is not None
    assert result["name"] == "flow"


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler")
def test_get_caller_branch_returns_none_when_no_detection(
    mock_json: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Returns None when neither CWD nor env var yields a branch."""
    no_branch_dir = tmp_path / "empty"
    no_branch_dir.mkdir()
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(no_branch_dir))
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)

    result = _id_mod.get_caller_branch()
    assert result is None


# ===========================================================================
# External citizens — fallback to the caller's own project registry
# ===========================================================================

_REGISTRY_ATTR = "aipass.commons.apps.handlers.identity.identity_ops.BRANCH_REGISTRY_PATH"


@pytest.fixture
def aipass_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An AIPass registry that knows @drone and nobody else."""
    aipass_root = tmp_path / "AIPass"
    aipass_root.mkdir()
    registry = _write_registry(
        aipass_root / "AIPASS_REGISTRY.json",
        [{"name": "DRONE", "path": "src/aipass/drone", "email": "@drone"}],
    )
    monkeypatch.setattr(_REGISTRY_ATTR, registry)
    return registry


def test_external_citizen_resolves_by_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """A branch absent from the AIPass registry resolves from the caller's registry."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is not None, "external citizen resolved to None — the bug this fix closes"
    assert result["name"] == "VERA"
    assert result["email"] == "@vera"


def test_external_citizen_resolves_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """Name lookup (drone's AIPASS_CALLER_BRANCH path) also reaches the caller's registry."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_by_name("vera")

    assert result is not None
    assert result["email"] == "@vera"


def test_external_citizen_absolute_registry_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path
):
    """Registries that store absolute branch paths resolve without being re-rooted."""
    project = tmp_path / "Vera-Studio"
    branch_dir = project / "branches" / "writer"
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    _write_registry(
        project / "VERA-STUDIO_REGISTRY.json",
        [{"name": "WRITER", "path": str(branch_dir), "email": "@writer"}],
    )
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is not None
    assert result["name"] == "WRITER"


def test_aipass_registry_wins_over_caller_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path
):
    """On a name collision the AIPass registry answers first — the fallback is a fallback."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project, name="DRONE", email="@not-our-drone")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_by_name("drone")

    assert result is not None
    assert result["email"] == "@drone"


def test_unknown_branch_still_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """A branch in neither registry still resolves to None — no silent invention."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    assert _id_mod.get_branch_info_by_name("nobody") is None


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler")
@patch("aipass.commons.apps.handlers.identity.identity_ops._ensure_agent_registered")
def test_get_caller_branch_end_to_end_for_external_citizen(
    mock_register: MagicMock,
    mock_json: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    aipass_registry: Path,
):
    """
    Full caller detection for an external citizen.

    This is the operation that used to fail: passport walk-up succeeded,
    every registry strategy returned None, and the citizen got no Commons
    identity at all. Name must come back normalized for authorship.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_caller_branch()

    assert result is not None
    assert result["name"] == "vera"
    assert result["email"] == "@vera"
    mock_register.assert_called_once()


# ---------------------------------------------------------------------------
# _find_caller_registries / _branches_from_registry
# ---------------------------------------------------------------------------


def test_find_caller_registries_skips_the_aipass_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The AIPass registry is consulted first, never again during the walk."""
    _write_registry(tmp_path / "AIPASS_REGISTRY.json", [])
    _write_registry(tmp_path / "VERA-STUDIO_REGISTRY.json", [])
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

    found = _ops._find_caller_registries()

    assert [p.name for p in found] == ["VERA-STUDIO_REGISTRY.json"]


def test_find_caller_registries_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Multiple registries in one directory resolve in deterministic order."""
    _write_registry(tmp_path / "ZEBRA_REGISTRY.json", [])
    _write_registry(tmp_path / "ALPHA_REGISTRY.json", [])
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

    found = _ops._find_caller_registries()

    assert [p.name for p in found] == ["ALPHA_REGISTRY.json", "ZEBRA_REGISTRY.json"]


def test_find_caller_registries_without_env(monkeypatch: pytest.MonkeyPatch):
    """No AIPASS_CALLER_CWD means no walk — nothing to search from."""
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    assert _ops._find_caller_registries() == []


def test_branches_from_registry_dict_shape(tmp_path: Path):
    """Dict-keyed branches are flattened to a list, like the list shape."""
    import json as json_mod

    path = tmp_path / "X_REGISTRY.json"
    path.write_text(
        json_mod.dumps({"branches": {"vera": {"name": "VERA", "path": "src/vera"}}}),
        encoding="utf-8",
    )

    branches = _ops._branches_from_registry(path)

    assert [b["name"] for b in branches] == ["VERA"]


def test_branches_from_registry_malformed_json(tmp_path: Path):
    """A corrupt registry is reported and skipped, never raised."""
    path = tmp_path / "X_REGISTRY.json"
    path.write_text("{not json", encoding="utf-8")

    assert _ops._branches_from_registry(path) == []


def test_branches_from_registry_missing_file(tmp_path: Path):
    """A registry path that doesn't exist yields no branches."""
    assert _ops._branches_from_registry(tmp_path / "nope.json") == []

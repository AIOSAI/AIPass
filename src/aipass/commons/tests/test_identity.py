# =================== AIPass ====================
# Name: test_identity.py
# Description: Unit tests for identity module and identity_ops handler
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-08-31
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


# ===========================================================================
# Case-insensitive filesystem widening — *_REGISTRY.json glob (fleet defect)
# ===========================================================================
#
# On Windows and default macOS the filesystem is case-insensitive, so
# ``directory.glob("*_REGISTRY.json")`` also returns ``*_registry.json``.
# The repo is full of bait: plan counters under flow_json/ and
# ``.spawn/.template_registry.json`` — and pathlib's ``*`` matches dotfiles,
# unlike the stdlib glob module, so the dotted one is reachable too.
#
# These pins were red on Linux before the fix. They stay meaningful on Linux
# because the widening is emulated rather than assumed: the instrument wraps
# Path.glob to also yield the case-folded pattern's matches, and a negative
# control proves the decoy is invisible without it.


@pytest.fixture
def case_insensitive_glob(monkeypatch: pytest.MonkeyPatch):
    """
    Emulate a case-insensitive filesystem for Path.glob.

    Yields the union of the pattern's matches and the case-folded
    pattern's matches — which is what Windows hands back for a single
    call. Wraps the real Path.glob rather than re-implementing listing,
    so production's own call site is what gets widened.
    """
    real_glob = Path.glob

    def widened(self, pattern, *args, **kwargs):
        seen = {}
        for found in real_glob(self, pattern, *args, **kwargs):
            seen[str(found)] = found
        folded = pattern.lower()
        if folded != pattern:
            for found in real_glob(self, folded, *args, **kwargs):
                seen[str(found)] = found
        return iter(sorted(seen.values()))

    monkeypatch.setattr(Path, "glob", widened)


def _plant_case_folded_decoy(project: Path, branch_dir: Path) -> Path:
    """
    Plant a lowercase registry that maps branch_dir to the WRONG citizen.

    Named .template_registry.json for two reasons: it is real bait from
    the fleet (@spawn writes one), and it sorts ahead of an uppercase
    project registry — so if the filter fails, the decoy is what answers,
    not merely what appears in a list.
    """
    decoy = project / ".template_registry.json"
    _write_registry(
        decoy,
        [{"name": "GHOST", "path": str(branch_dir), "email": "@ghost", "description": "should never resolve"}],
    )
    return decoy


def test_case_folded_registry_cannot_answer_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path, case_insensitive_glob
):
    """
    On a case-insensitive filesystem the decoy is listed — it must not ANSWER.

    The assertion is about what identity resolution returns, not about set
    membership, because the failure that matters is a citizen resolving to
    the wrong name.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    _plant_case_folded_decoy(project, branch_dir)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is not None, "external citizen stopped resolving entirely"
    assert result["name"] == "VERA", (
        f"case-folded decoy answered identity: got {result['name']!r} — "
        "the *_REGISTRY.json glob widened on a case-insensitive filesystem"
    )
    assert result["email"] == "@vera"


def test_case_folded_registry_excluded_from_caller_registries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_insensitive_glob
):
    """The decoy is filtered at the source, so no later matcher can reach it."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    decoy = _plant_case_folded_decoy(project, branch_dir)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    found = _ops._find_caller_registries()

    assert decoy not in found, "case-folded registry survived the suffix filter"
    assert [p.name for p in found] == ["VERA-STUDIO_REGISTRY.json"]


# The pattern production actually globs, and a probe file whose suffix is the
# lowercase form of it. Named constants because the DIRECTION is the claim -
# see test_the_host_probe_travels_the_defects_direction below.
_PRODUCTION_GLOB = "*_REGISTRY.json"
_PROBE_FILENAME = "hostprobe_registry.json"


def _host_folds_glob_case(tmp_path: Path) -> bool:
    """
    Probe the host: does its glob fold case? Never assume, never skipif.

    The probe travels the DEFECT'S OWN DIRECTION (@ai_mail's round-4 lesson):
    a lowercase file, matched against the uppercase pattern — which is exactly
    what production asks the filesystem. Probing the other way round measures
    a different question and can answer it differently.

    The probe lives in its own directory so it cannot collide with, or be
    collided by, any registry a test planted. Its stem is deliberately
    distinct: on a folding filesystem names differing only by case CANNOT
    coexist (@memory), so a case-twin probe would overwrite a real file's
    contents while the directory kept the original spelling.
    """
    probe_dir = tmp_path / "_case_probe"
    probe_dir.mkdir(exist_ok=True)
    probe = probe_dir / _PROBE_FILENAME
    probe.write_text("{}", encoding="utf-8")
    try:
        return probe in set(probe_dir.glob(_PRODUCTION_GLOB))
    finally:
        probe.unlink()


def test_the_widening_instrument_actually_widens(tmp_path: Path, case_insensitive_glob):
    """
    POSITIVE CONTROL — the instrument, exercised through production's own call.

    This makes the exact call ``_find_caller_registries`` makes rather than
    re-stating its logic. If this fails, the pins above prove nothing and are
    green for the wrong reason.

    On a folding host this control is satisfied by the filesystem itself
    rather than by the instrument — which is not a defect but is worth
    knowing. The negative control below names which world the run is in.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    decoy = _plant_case_folded_decoy(project, branch_dir)

    listed = list(project.glob("*_REGISTRY.json"))

    assert decoy in listed, "instrument did not widen — the case-insensitive emulation is broken"
    assert project / "VERA-STUDIO_REGISTRY.json" in listed


def test_raw_glob_matches_what_the_host_filesystem_actually_does(tmp_path: Path):
    """
    NEGATIVE CONTROL — without the instrument, the host's own answer.

    The earlier spelling of this test asserted the decoy is invisible, full
    stop. That is true on Linux and FALSE on NTFS and default macOS — so the
    control failed on the exact host the defect lives on, which is the one
    place a control must not fail. Per @memory's ruling the host is PROBED,
    never skipped, and both outcomes are pinned:

      - case-sensitive host: the decoy is invisible, so the pins above are
        measuring the fix and not the filesystem — the instrument is load-
        bearing and the positive control proves it widens.
      - case-folding host: the decoy is listed for real. The widening is
        native, the emulation is redundant, and the pins above are measuring
        the defect's actual home.

    Either way the production filter is what must exclude it, and
    ``test_case_folded_registry_excluded_from_caller_registries`` above
    asserts that on both hosts.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    decoy = _plant_case_folded_decoy(project, branch_dir)

    listed = list(project.glob("*_REGISTRY.json"))
    real_registry = project / "VERA-STUDIO_REGISTRY.json"

    if _host_folds_glob_case(tmp_path):
        assert decoy in listed, (
            "the host folds glob case for a lowercase probe but not for the "
            "decoy — the probe and the decoy disagree about the same filesystem"
        )
        assert real_registry in listed
    else:
        assert decoy not in listed
        assert listed == [real_registry]


def test_the_host_probe_travels_the_defects_direction():
    """
    The probe's DIRECTION is the claim, and this host cannot measure it.

    @ai_mail's round-4 lesson: the probe must ask the filesystem the same
    question production asks — a lowercase file against the UPPERCASE
    pattern. Reversed (an uppercase file against a lowercase pattern) it
    measures a different question, and a host that folds only one way would
    answer it differently.

    On a case-sensitive host both directions return False, so reversing the
    probe changes no behavioural outcome here and no behavioural pin can
    catch it. Stated honestly: this is a SHAPE pin, deliberately weaker than
    the rest of this block. It exists so the direction cannot be silently
    reversed by someone who does not know why it was chosen.
    """
    assert _PRODUCTION_GLOB == "*_REGISTRY.json"
    assert _PROBE_FILENAME.endswith("_registry.json"), (
        "the probe file must carry the LOWERCASE suffix — it is the decoy's "
        "spelling, and the glob pattern is production's"
    )
    assert _PRODUCTION_GLOB.lstrip("*") not in _PROBE_FILENAME, (
        "probe and pattern must differ in case, or nothing is being probed"
    )

    # The pattern is production's own, read from the source rather than
    # re-typed: a pin on a copy of a constant survives the constant changing.
    source = Path(_ops.__file__).read_text(encoding="utf-8")
    assert f'directory.glob("{_PRODUCTION_GLOB}")' in source, (
        "production no longer globs this pattern — the host probe is asking a question nothing asks any more"
    )


def test_external_registries_with_lowercase_stems_still_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path, case_insensitive_glob
):
    """
    The filter is on the SUFFIX, never the stem.

    External projects name registries after themselves, so a lowercase or
    mixed-case stem is legitimate — only the _REGISTRY.json suffix carries
    the meaning. A stem-based filter would delete a real citizen.
    """
    project = tmp_path / "vera_studio"
    project.mkdir()
    branch_dir = project / "src" / "app"
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    _write_registry(
        project / "vera_studio_REGISTRY.json",
        [{"name": "APP", "path": "src/app", "email": "@app"}],
    )
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is not None, "a lowercase-stem registry was wrongly filtered out"
    assert result["email"] == "@app"

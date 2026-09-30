# =================== AIPass ====================
# Name: test_identity.py
# Description: Unit tests for identity module and identity_ops handler
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/commons_identity.py and apps/handlers/identity/identity_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that commons_identity.py and identity_ops.py parse and import

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.commons.apps.modules import commons_identity as _id_mod
from aipass.commons.apps.handlers.identity import identity_ops as _ops


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


def test_extract_mentions_answers_none_when_the_lookup_fails():
    """A failed agents lookup answers None, never the [] of "nobody was mentioned".

    Before: the except returned [], so post_ops/comment_ops reported a post that
    named @drone as mentioning no one and the mention was lost in silence.
    Mutant: identity_ops `return None` -> `return []` in the except turns this red.
    """
    with patch(
        "aipass.commons.apps.handlers.database.db.get_db",
        side_effect=sqlite3.OperationalError("database is locked"),
    ) as failing_get_db:
        result = _id_mod.extract_mentions("Hey @drone check this out")

    failing_get_db.assert_called_once_with()
    assert result is None


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


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler", autospec=True)
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


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler", autospec=True)
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
    mock_register.assert_called_once()


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler", autospec=True)
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


@patch("aipass.commons.apps.handlers.identity.identity_ops.json_handler", autospec=True)
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


def test_find_caller_registries_skips_the_aipass_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path
):
    """
    The AIPass registry is consulted first, never again during the walk.

    Through get_branch_info_by_name: an AIPASS_REGISTRY.json met on the walk
    up from the caller's cwd is not the caller's project registry, so a name
    only it holds never resolves.
    Mutant killed: dropping `and path.name != "AIPASS_REGISTRY.json"` from
    _find_caller_registries (GHOST resolves from the walked AIPass registry).
    """
    _write_registry(tmp_path / "AIPASS_REGISTRY.json", [{"name": "GHOST", "path": "ghost", "email": "@ghost"}])
    _write_registry(tmp_path / "VERA-STUDIO_REGISTRY.json", [{"name": "VERA", "path": "vera", "email": "@vera"}])
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

    assert _id_mod.get_branch_info_by_name("ghost") is None
    result = _id_mod.get_branch_info_by_name("vera")
    assert result is not None
    assert result["email"] == "@vera"


def test_find_caller_registries_sorted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """
    Multiple registries in one directory resolve in deterministic order.

    Both registries hold a VERA; the alphabetically first registry answers,
    whatever order the filesystem lists them in.
    Mutant killed: `return matches` -> `return matches[::-1]` in
    _find_caller_registries (ZEBRA's VERA answers).
    """
    _write_registry(tmp_path / "ZEBRA_REGISTRY.json", [{"name": "VERA", "path": "vera", "email": "@zebra-vera"}])
    _write_registry(tmp_path / "ALPHA_REGISTRY.json", [{"name": "VERA", "path": "vera", "email": "@alpha-vera"}])
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

    result = _id_mod.get_branch_info_by_name("vera")

    assert result is not None
    assert result["email"] == "@alpha-vera"


def test_find_caller_registries_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """No AIPASS_CALLER_CWD means no walk: a project registry at the process cwd is never searched."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    monkeypatch.chdir(branch_dir)

    assert _id_mod.get_branch_info_by_name("vera") is None


def test_branches_from_registry_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    A registry path that doesn't exist yields no branches.

    Through get_branch_info_by_name: the AIPass registry pointed at a missing
    file, no caller walk — the lookup answers None, it does not raise.
    Mutant killed: the missing-file `return []` in _branches_from_registry
    -> `raise FileNotFoundError(registry_path)`.
    """
    monkeypatch.setattr(_REGISTRY_ATTR, tmp_path / "nope.json")
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    assert _id_mod.get_branch_info_by_name("vera") is None


def test_branches_from_registry_dict_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """Dict-keyed branches are flattened to a list, like the list shape."""
    import json as json_mod

    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = project / "src" / "vera"
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    (project / "VERA-STUDIO_REGISTRY.json").write_text(
        json_mod.dumps({"branches": {"vera": {"name": "VERA", "path": "src/vera"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is not None
    assert result["name"] == "VERA"


def test_branches_from_registry_malformed_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path):
    """A corrupt registry is reported and skipped, never raised."""
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = project / "src" / "vera"
    (branch_dir / ".trinity").mkdir(parents=True)
    (branch_dir / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    (project / "VERA-STUDIO_REGISTRY.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_from_registry(branch_dir)

    assert result is None


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
def case_insensitive_glob(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, list[Path]]]:
    """
    Emulate a case-insensitive filesystem for the registry listing.

    Yields the union of the pattern's matches and the case-folded
    pattern's matches — which is what Windows hands back for a single
    call. Replaces identity_ops.list_registry_candidates (the seam whose
    body is production's one glob) rather than Path.glob, so only the
    registry listing is widened, never every glob in the process.

    Returns the recorder: one (directory, listing) pair per call production
    made to the seam, so a test can prove production went through it.
    """
    pattern = "*_REGISTRY.json"
    calls: list[tuple[Path, list[Path]]] = []

    def widened(directory: Path):
        seen = {}
        for found in directory.glob(pattern):
            seen[str(found)] = found
        for found in directory.glob(pattern.lower()):
            seen[str(found)] = found
        listing = sorted(seen.values())
        calls.append((directory, listing))
        return iter(listing)

    monkeypatch.setattr(_ops, "list_registry_candidates", widened)
    return calls


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aipass_registry: Path, case_insensitive_glob
):
    """
    The decoy is filtered at the source, so no later matcher can reach it.

    Through get_branch_info_by_name: the decoy's only citizen, GHOST, never
    resolves by name, while the real project registry still answers VERA.
    Mutant killed: `if path.name.endswith("_REGISTRY.json")` ->
    `if path.name.lower().endswith("_registry.json")` in _find_caller_registries.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    _plant_case_folded_decoy(project, branch_dir)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    assert _id_mod.get_branch_info_by_name("ghost") is None, "case-folded registry survived the suffix filter"
    result = _id_mod.get_branch_info_by_name("vera")
    assert result is not None
    assert result["name"] == "VERA"


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


def test_the_widening_instrument_actually_widens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    aipass_registry: Path,
    case_insensitive_glob: list[tuple[Path, list[Path]]],
):
    """
    POSITIVE CONTROL — the instrument is what production lists registries through.

    get_branch_info_by_name on the planted project must reach the stand-in and
    be handed the decoy; if production globs on its own, the pins above prove
    nothing and are green for the wrong reason (commons' decision, DPLAN-0354 leg 4).

    On a folding host the decoy is listed by the filesystem itself as well —
    not a defect, but worth knowing. The negative control below names which
    world the run is in.
    """
    project = tmp_path / "Vera-Studio"
    project.mkdir()
    branch_dir = _make_external_project(project)
    decoy = _plant_case_folded_decoy(project, branch_dir)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch_dir))

    result = _id_mod.get_branch_info_by_name("vera")

    listings = dict(case_insensitive_glob)
    listed = listings.get(project.resolve(), [])
    assert decoy.resolve() in listed, "production did not list registries through the widened stand-in"
    assert (project / "VERA-STUDIO_REGISTRY.json").resolve() in listed
    assert result is not None
    assert result["name"] == "VERA"


def test_list_registry_candidates_lists_one_level_of_registry_files_only(tmp_path: Path):
    """The seam by name, no fixture (commons' decision, DPLAN-0354 leg 4b, door A); its proof is its two mutants."""
    (tmp_path / "ALPHA_REGISTRY.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "BETA_REGISTRY.json").write_text("{}", encoding="utf-8")

    listed = list(_ops.list_registry_candidates(tmp_path))

    assert listed == [tmp_path / "ALPHA_REGISTRY.json"]


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


def test_get_caller_branch_raises_a_named_failure_when_the_lookup_breaks():
    """A broken lookup raises CallerLookupFailed; None stays "no branch detected".

    Before (DPLAN-0354 leg 3): the except logged and returned None, the same answer
    as "not run from a branch", so ~30 handlers told the user the wrong thing.
    Mutant: identity_ops `raise CallerLookupFailed(...) from e` -> `return None` turns this red.
    """
    with patch.object(_ops, "find_branch_root", side_effect=OSError("registry unreadable")) as lookup:
        with pytest.raises(_ops.CallerLookupFailed, match="Caller lookup failed: registry unreadable"):
            _ops.get_caller_branch()

    lookup.assert_called_once()


def test_whoami_refuses_naming_a_failed_caller_lookup(capsys: pytest.CaptureFixture[str]):
    """whoami names a broken lookup instead of "run from a branch directory"."""
    # whoami's one database route is identity_ops' lazy import of db.get_db; guarded there.
    with (
        patch.object(_ops, "find_branch_root", side_effect=OSError("registry unreadable")),
        patch("aipass.commons.apps.handlers.database.db.get_db") as db,
    ):
        assert _id_mod.handle_command("whoami", []) is True

    db.assert_not_called()
    err = " ".join(capsys.readouterr().err.split())
    assert "Caller lookup failed: registry unreadable" in err
    assert "Run from a branch directory" not in err

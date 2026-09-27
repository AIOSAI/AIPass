# =================== AIPass ====================
# Name: test_push_central.py
# Description: Tests for push_central handler -- push to Plans Central
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/dashboard/push_central.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import Path
from unittest.mock import patch

import aipass.flow.apps.handlers.dashboard.push_central as mod
from aipass.flow.apps.handlers import repo_root
from aipass.flow.apps.handlers.repo_root import find_repo_root

_MOD = "aipass.flow.apps.handlers.dashboard.push_central"
_DISCOVER = "aipass.flow.apps.handlers.template.plan_type_loader.discover_plan_types"


def _row(prefix, number, branch, status="open", **extra):
    """One registry row on disk, keyed as the real registries key it (bare number)."""
    row = {
        "subject": f"{prefix}-{number:04d}",
        "status": status,
        "created": "2026-04-20",
        "file_path": f"/repo/src/aipass/{branch}/{prefix}-{number:04d}_x.md",
        "location": f"/repo/src/aipass/{branch}",
    }
    row.update(extra)
    return row


def _push(tmp_path, registries=None, plan_types=None, central=None):
    """Run the PUBLIC push against a tmp_path world; return what it wrote.

    Every path the push touches is redirected before it runs: FLOW_JSON_DIR (the
    registries it reads), AI_CENTRAL_DIR and CENTRAL_FILE (the file it writes).
    ``aggregate_central_impl`` stays patched — with heal=True it auto-closes rows
    in live branch registries — and is asserted, never discarded.

    Args:
        registries: filename -> dict (written as JSON) or str/bytes (written raw).
        plan_types: what discover_plan_types answers; an Exception is raised
            instead. Defaults to one type per registry written.
        central: an existing PLANS.central.json, dict or raw bytes.

    Returns:
        (push result, parsed PLANS.central.json)
    """
    registries = registries or {}
    flow_json = tmp_path / "flow_json"
    flow_json.mkdir(exist_ok=True)
    for name, data in registries.items():
        raw = data if isinstance(data, (str, bytes)) else json.dumps(data)
        (flow_json / name).write_bytes(raw.encode("utf-8") if isinstance(raw, str) else raw)
    ai_central = tmp_path / ".ai_central"
    central_file = ai_central / "PLANS.central.json"
    if central is not None:
        ai_central.mkdir()
        central_file.write_bytes(central if isinstance(central, bytes) else json.dumps(central).encode("utf-8"))
    if plan_types is None:
        plan_types = {name: {"registry_file": name} for name in registries}
    discover = (
        patch(_DISCOVER, side_effect=plan_types)
        if isinstance(plan_types, Exception)
        else patch(_DISCOVER, return_value=plan_types)
    )
    with (
        patch.object(mod, "FLOW_JSON_DIR", flow_json),
        patch.object(mod, "AI_CENTRAL_DIR", ai_central),
        patch.object(mod, "CENTRAL_FILE", central_file),
        discover,
        patch.object(mod, "aggregate_central_impl") as mock_agg,
    ):
        result = mod.push_to_plans_central()
    mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
    return result, json.loads(central_file.read_text(encoding="utf-8"))


def _branches(tmp_path, registry):
    """Push a merged-shape registry ({"FPLAN-0001": row}) and return the written branches.

    Each composite key is split back to how it lives on disk — ``fplan_registry.json``
    keyed ``"0001"`` — so the push reads it through its own loader.
    """
    on_disk = {}
    for key, row in registry.get("plans", {}).items():
        prefix, number = key.rsplit("-", 1)
        on_disk.setdefault(f"{prefix.lower()}_registry.json", {"plans": {}})["plans"][number] = row
    result, written = _push(tmp_path, on_disk)
    assert result is True
    return written["branches"]


def _plan_ids(written):
    """Every plan id the push wrote, active and recently closed, across branches."""
    return {
        plan["plan_id"]
        for section in written["branches"].values()
        for plan in section["active_plans"] + section["recently_closed"]
    }


# =============================================
# 1. _find_repo_root
# =============================================


class TestFindRepoRoot:
    """``push_central._find_repo_root`` — now a delegation, not a private walk.

    REWRITTEN 2026-08-31. Flow carried SEVEN near-identical private
    ``_find_repo_root`` copies, each ending ``return Path.cwd()``, and six were
    called at MODULE level. These tests patched ``push_central.__file__`` to
    steer that private walk; the walk lives in ``handlers/repo_root`` now, so
    the patch no longer reaches it and the cases had to move with the code.

    ``test_falls_back_to_cwd_when_no_marker`` is REVERSED below rather than
    deleted. It asserted ``result == Path.cwd()`` and was GREEN — a test
    standing guard over the exact construct that takes CI down on a box whose
    working directory is gone, and that silently resolves a WRITER against
    whatever directory the caller's shell was pointing at when no registry
    exists. @memory found the same reversed test in their own tree the same
    week. The contract it pinned was wrong; the test now pins the correct one
    and says why, so nobody restores the old assertion thinking they found a
    regression.
    """

    def test_delegates_to_the_one_implementation(self):
        """The private copy is gone: the central file must sit under the shared answer.

        Read through what the delegation builds at import — the public
        ``AI_CENTRAL_DIR`` / ``CENTRAL_FILE`` the push writes — not the helper.
        Mutant: find_repo_root(caller="push_central") -> Path("/elsewhere") reddens this.
        """
        root = repo_root.find_repo_root()
        assert mod.AI_CENTRAL_DIR == root / ".ai_central"
        assert mod.CENTRAL_FILE == root / ".ai_central" / "PLANS.central.json"

    def test_returns_dir_containing_registry(self, tmp_path):
        """Returns the directory containing AIPASS_REGISTRY.json."""
        marker = tmp_path / "AIPASS_REGISTRY.json"
        marker.write_text("{}", encoding="utf-8")
        child = tmp_path / "a" / "b" / "c"
        child.mkdir(parents=True)

        assert find_repo_root(child) == tmp_path

    def test_finds_marker_in_immediate_parent(self, tmp_path):
        """Finds AIPASS_REGISTRY.json in the immediate parent directory."""
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        (parent_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        child_dir = parent_dir / "child"
        child_dir.mkdir()

        assert find_repo_root(child_dir) == parent_dir

    def test_never_falls_back_to_cwd_when_no_marker(self, tmp_path, monkeypatch):
        """THE REVERSED TEST. No marker anywhere → the SOURCE tree, never cwd.

        The old assertion was ``result == Path.cwd()``. Both defects it blessed
        are pinned here: the process directory is not consulted at all (so a
        deleted cwd cannot kill a module-level caller), and the answer does not
        move when the caller's shell moves (so a writer cannot be steered into a
        tree nobody chose).
        """
        sub = tmp_path / "sub"
        sub.mkdir()

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        # A real chdir, not a patch over pathlib: the process directory really
        # is ``elsewhere`` for the call, and monkeypatch restores it after.
        monkeypatch.chdir(elsewhere)

        result = repo_root.find_repo_root(sub)

        assert result == repo_root.SOURCE_ROOT
        assert result != elsewhere, "the walk is still answering with the process directory"

    def test_the_cwd_stand_in_is_live(self, tmp_path, monkeypatch):
        """Control: a process directory that HOLDS the marker still steers nothing.

        The test above would pass vacuously if the walk consulted the cwd only
        when a marker sits there; here one does, and the answer must not move.
        """
        sub = tmp_path / "sub"
        sub.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / repo_root.CORE_REGISTRY).write_text("{}", encoding="utf-8")
        monkeypatch.chdir(elsewhere)
        assert Path.cwd() == elsewhere

        assert repo_root.find_repo_root(sub) == repo_root.SOURCE_ROOT


class TestTheBareWorldIsStatedNotInherited:
    """Both marker worlds are asserted here, so neither is inherited from the host.

    ``AIPASS_REGISTRY.json`` is gitignored and machine-local. Every test above
    ran on a machine that HAS it, and that is exactly how
    ``test_success_returns_true`` shipped green and reddened all four Python
    versions on CI (round 5, @devpulse): with no marker the walk takes the
    fallback, the fallback LOGS, and the autouse ``mock_json_handler`` counted
    two calls where the test pinned one. The production code was right the whole
    time; the assertion was measuring the host.

    The count assertions are fixed in ``tests/conftest.py`` — the six
    module-level callers are pre-imported, so the import-time diagnostic can
    never land in a test window. These two tests are the other half: they say
    out loud what the bare world DOES, so it is a pinned behaviour rather than a
    condition nobody on a dev box ever sees.
    """

    def test_no_marker_means_source_root_and_a_logged_fallback(self, monkeypatch):
        """Marker absent → SOURCE_ROOT, said out loud, never the process cwd."""
        asked = []

        def deny_marker(path):
            """Deny only the marker; answer every other name truthfully."""
            asked.append(Path(path).name)
            return Path(path).name != repo_root.CORE_REGISTRY and Path(path).exists()

        monkeypatch.setattr(repo_root, "exists_exactly", deny_marker)
        logged = []
        monkeypatch.setattr(
            repo_root,
            "_record_fallback",
            lambda caller, marker, current: logged.append((caller, marker)),
        )

        result = repo_root.find_repo_root(caller="push_central")

        assert result == repo_root.SOURCE_ROOT
        assert asked and set(asked) == {repo_root.CORE_REGISTRY}, "the walk never asked for the marker"
        assert logged == [("push_central", repo_root.CORE_REGISTRY)], (
            "the fallback did not announce itself — a fallback nobody can see is how the next one survives"
        )

    def test_the_marker_denial_is_live(self, tmp_path, monkeypatch):
        """Control: a denial that never bites makes the test above vacuous."""
        marker = tmp_path / repo_root.CORE_REGISTRY
        marker.write_text("{}", encoding="utf-8")
        assert repo_root.find_repo_root(tmp_path) == tmp_path

        monkeypatch.setattr(
            repo_root, "exists_exactly", lambda path: Path(path).name != repo_root.CORE_REGISTRY and Path(path).exists()
        )
        assert repo_root.find_repo_root(tmp_path) == repo_root.SOURCE_ROOT

    def test_the_fallback_records_without_ever_raising(self, tmp_path, mock_json_handler, monkeypatch):
        """Six callers reach _record_fallback at IMPORT time.

        A diagnostic write that fails in a bare world must not become the import
        crash the module exists to prevent, so the real recorder is exercised
        here with its json_handler dead.

        The dead handler is the autouse spy told to raise, NOT a second
        monkeypatch on the same attribute: monkeypatch is one shared instance
        that mock_logger already took, so it is torn down AFTER the spy's
        patch exits and would put the spy's MagicMock back onto the shim for
        good. That leak was invisible while flow ran alone and reddened
        seedgo's contract for [flow] the moment both shared one process
        (CI coverage leg, DPLAN-0325 pair 7).
        """

        def explode(*args, **kwargs):
            raise OSError("no writable tree")

        mock_json_handler.side_effect = explode
        # The walk is reached through its public door with the marker denied,
        # so the REAL recorder runs on the fallback branch it guards.
        monkeypatch.setattr(
            repo_root, "exists_exactly", lambda path: Path(path).name != repo_root.CORE_REGISTRY and Path(path).exists()
        )

        # MUST NOT RAISE, and that is now stated rather than merely survived:
        # the walk still answers, and the exploding handler must actually have
        # been REACHED. Without the second assertion a recorder that returned
        # early - never touching the diagnostic write at all - passed this test
        # while proving nothing about the bare world it exists for.
        # Mutant: the recorder's `except Exception` -> `except ImportError` reddens this.
        assert repo_root.find_repo_root(tmp_path / "nowhere", caller="push_central") == repo_root.SOURCE_ROOT
        assert mock_json_handler.call_args[0][0] == "repo_root_fallback"


# =============================================
# 2. _get_all_registry_files
# =============================================


class TestGetAllRegistryFiles:
    """Tests for _get_all_registry_files."""

    def test_returns_discovered_registry_files(self, tmp_path):
        """Every discovered type's registry is read — and nothing undiscovered is.

        Mutant: `files.append(rf)` -> `files[:] = [rf]` reddens this.
        """
        mock_types = {
            "flow_plans": {"registry_file": "fplan_registry.json"},
            "dev_plans": {"registry_file": "dplan_registry.json"},
        }
        result, written = _push(
            tmp_path,
            {
                "fplan_registry.json": {"plans": {"1": _row("FPLAN", 1, "flow")}},
                "dplan_registry.json": {"plans": {"2": _row("DPLAN", 2, "devpulse")}},
                "xplan_registry.json": {"plans": {"3": _row("XPLAN", 3, "stray")}},
            },
            plan_types=mock_types,
        )

        assert result is True
        assert _plan_ids(written) == {"FPLAN-0001", "DPLAN-0002"}

    def test_deduplicates_registry_files(self):
        """Does not duplicate registry filenames when multiple types share the same file."""
        mock_types = {
            "flow_plans": {"registry_file": "fplan_registry.json"},
            "flow_plans_v2": {"registry_file": "fplan_registry.json"},
        }
        with patch(
            "aipass.flow.apps.handlers.template.plan_type_loader.discover_plan_types",
            return_value=mock_types,
        ):
            result = mod._get_all_registry_files()

        assert result.count("fplan_registry.json") == 1

    def test_falls_back_on_discovery_exception(self, tmp_path):
        """Falls back to REGISTRY_FILE.name when discover_plan_types raises.

        Mutant: `return [REGISTRY_FILE.name]` -> `return []` reddens this.
        """
        result, written = _push(
            tmp_path,
            {
                mod.REGISTRY_FILE.name: {"plans": {"1": _row("FPLAN", 1, "flow")}},
                "dplan_registry.json": {"plans": {"2": _row("DPLAN", 2, "devpulse")}},
            },
            plan_types=RuntimeError("boom"),
        )

        assert result is True
        assert _plan_ids(written) == {"FPLAN-0001"}

    def test_falls_back_when_no_registry_file_key(self, tmp_path):
        """Falls back to default when config dicts lack registry_file key."""
        mock_types = {
            "flow_plans": {"prefix": "FPLAN"},
            "dev_plans": {"prefix": "DPLAN"},
        }
        result, written = _push(
            tmp_path,
            {
                mod.REGISTRY_FILE.name: {"plans": {"1": _row("FPLAN", 1, "flow")}},
                "dplan_registry.json": {"plans": {"2": _row("DPLAN", 2, "devpulse")}},
            },
            plan_types=mock_types,
        )

        # No registry_file keys, so files list is empty -> fallback
        assert result is True
        assert _plan_ids(written) == {"FPLAN-0001"}

    def test_skips_none_registry_file(self, tmp_path):
        """Skips entries where registry_file is None — the push does not die on it."""
        mock_types = {
            "flow_plans": {"registry_file": "fplan_registry.json"},
            "special": {"registry_file": None},
        }
        result, written = _push(
            tmp_path,
            {"fplan_registry.json": {"plans": {"1": _row("FPLAN", 1, "flow")}}},
            plan_types=mock_types,
        )

        assert result is True
        assert _plan_ids(written) == {"FPLAN-0001"}


# =============================================
# 3. _load_registry
# =============================================


class TestLoadRegistry:
    """Tests for _load_registry."""

    def test_merges_multiple_registries(self, tmp_path):
        """Merges plans from multiple registry files using composite keys.

        Two registries sharing plan number 1 must stay two plans (the collision
        the composite key exists for). Mutant: `f"{prefix}-{plan_num.zfill(4)}"`
        -> `plan_num` reddens this.
        """
        result, written = _push(
            tmp_path,
            {
                "fplan_registry.json": {"plans": {"1": _row("FPLAN", 1, "flow")}, "next_number": 5},
                "dplan_registry.json": {"plans": {"1": _row("DPLAN", 1, "flow")}, "next_number": 10},
            },
        )

        assert result is True
        assert _plan_ids(written) == {"FPLAN-0001", "DPLAN-0001"}

    def test_handles_missing_registry(self, tmp_path, mock_logger):
        """Gracefully handles a missing registry file — silently, not as a failure.

        Without the exists() guard the open raises, is caught and the push still
        succeeds, so the absent warning is what tells the two apart.
        Mutant: `if not target.exists():` -> `if False:` reddens this.
        """
        result, written = _push(tmp_path, plan_types={"x": {"registry_file": "nonexistent_registry.json"}})

        assert result is True
        assert written["branches"] == {}
        mock_logger.warning.assert_not_called()

    def test_keeps_highest_next_number(self, tmp_path):
        """Keeps the highest next_number across registries."""
        reg_a = {"plans": {}, "next_number": 3}
        reg_b = {"plans": {}, "next_number": 50}
        reg_c = {"plans": {}, "next_number": 20}
        (tmp_path / "a_registry.json").write_text(json.dumps(reg_a), encoding="utf-8")
        (tmp_path / "b_registry.json").write_text(json.dumps(reg_b), encoding="utf-8")
        (tmp_path / "c_registry.json").write_text(json.dumps(reg_c), encoding="utf-8")

        with (
            patch.object(mod, "FLOW_JSON_DIR", tmp_path),
            patch.object(
                mod,
                "_get_all_registry_files",
                return_value=["a_registry.json", "b_registry.json", "c_registry.json"],
            ),
        ):
            result = mod._load_registry()
        assert result["next_number"] == 50

    def test_handles_corrupt_registry_gracefully(self, tmp_path):
        """Skips a corrupt registry file and continues with others."""
        result, written = _push(
            tmp_path,
            {
                "bad_registry.json": "not json!",
                "good_registry.json": {"plans": {"1": _row("GOOD", 1, "flow")}, "next_number": 5},
            },
        )

        # Mutant: the per-file `except Exception` -> `except KeyError` reddens this.
        assert result is True
        assert _plan_ids(written) == {"GOOD-0001"}

    def test_uses_prefix_from_filename(self, tmp_path):
        """Extracts prefix from plan file_path filename, not the registry's name."""
        result, written = _push(
            tmp_path,
            {
                "other_registry.json": {
                    "plans": {"7": _row("XPLAN", 7, "flow", file_path=str(tmp_path / "XPLAN-0007_test.md"))}
                }
            },
        )

        assert _plan_ids(written) == {"XPLAN-0007"}

    def test_fallback_prefix_from_registry_filename(self, tmp_path):
        """Uses registry filename prefix when file_path has no recognizable prefix."""
        result, written = _push(
            tmp_path,
            {
                "custom_registry.json": {
                    "plans": {"3": _row("CUSTOM", 3, "flow", file_path=str(tmp_path / "some_file.md"))}
                }
            },
        )

        # Falls back to CUSTOM (from custom_registry.json -> custom -> CUSTOM)
        assert _plan_ids(written) == {"CUSTOM-0003"}

    def test_empty_registry_plans(self, tmp_path):
        """Handles registry file with empty plans dict."""
        result, written = _push(tmp_path, {"fplan_registry.json": {"plans": {}, "next_number": 1}})

        assert result is True
        assert written["branches"] == {}

    def test_plan_with_empty_file_path(self, tmp_path):
        """Handles plan with empty file_path string."""
        result, written = _push(
            tmp_path,
            {"fplan_registry.json": {"plans": {"1": _row("FPLAN", 1, "flow", file_path="")}, "next_number": 2}},
        )

        # Falls back to FPLAN prefix from registry filename
        assert _plan_ids(written) == {"FPLAN-0001"}


# =============================================
# 4. _extract_plans_by_branch
# =============================================


class TestExtractPlansByBranch:
    """Tests for _extract_plans_by_branch."""

    def test_groups_plans_by_branch(self, tmp_path):
        """Groups plans into per-branch sections by location path name."""
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Flow plan",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/p/FPLAN-0001.md",
                    "location": "/repo/src/aipass/flow",
                },
                "DPLAN-0001": {
                    "subject": "Devpulse plan",
                    "status": "open",
                    "created": "2026-04-21",
                    "file_path": "/p/DPLAN-0001.md",
                    "location": "/repo/src/aipass/devpulse",
                },
            }
        }
        result = _branches(tmp_path, registry)
        assert "flow" in result
        assert "devpulse" in result
        assert result["flow"]["statistics"]["active_count"] == 1
        assert result["devpulse"]["statistics"]["active_count"] == 1

    def test_extracts_active_and_closed(self, tmp_path):
        """Separates active and closed plans within a branch."""
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Open",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/p/FPLAN-0001.md",
                    "location": "/repo/src/aipass/flow",
                },
                "FPLAN-0002": {
                    "subject": "Closed",
                    "status": "closed",
                    "created": "2026-04-15",
                    "closed": "2026-04-18",
                    "closed_reason": "done",
                    "file_path": "/p/FPLAN-0002.md",
                    "location": "/repo/src/aipass/flow",
                },
            }
        }
        result = _branches(tmp_path, registry)
        flow = result["flow"]
        assert flow["statistics"]["active_count"] == 1
        assert flow["statistics"]["total_closed"] == 1
        assert len(flow["active_plans"]) == 1
        assert len(flow["recently_closed"]) == 1
        assert flow["recently_closed"][0]["closed"] == "2026-04-18"

    def test_sorts_active_newest_first(self, tmp_path):
        """Active plans sorted by created date, newest first."""
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Oldest",
                    "status": "open",
                    "created": "2026-04-01",
                    "file_path": "/p/FPLAN-0001.md",
                    "location": "/repo/src/aipass/flow",
                },
                "FPLAN-0002": {
                    "subject": "Newest",
                    "status": "open",
                    "created": "2026-04-25",
                    "file_path": "/p/FPLAN-0002.md",
                    "location": "/repo/src/aipass/flow",
                },
            }
        }
        result = _branches(tmp_path, registry)
        active = result["flow"]["active_plans"]
        assert active[0]["subject"] == "Newest"
        assert active[1]["subject"] == "Oldest"

    def test_closed_limited_to_5(self, tmp_path):
        """Recently closed plans limited to 5 per branch."""
        plans = {}
        for i in range(1, 9):
            plans[f"FPLAN-{str(i).zfill(4)}"] = {
                "subject": f"Closed {i}",
                "status": "closed",
                "created": "2026-04-01",
                "closed": f"2026-04-{str(i + 10).zfill(2)}",
                "file_path": f"/p/FPLAN-{str(i).zfill(4)}.md",
                "location": "/repo/src/aipass/flow",
            }
        result = _branches(tmp_path, {"plans": plans})
        # Mutant: `closed[:5]` -> `closed[:6]` reddens this.
        assert len(result["flow"]["recently_closed"]) == 5
        assert result["flow"]["statistics"]["total_closed"] == 8

    def test_empty_registry(self, tmp_path):
        """Returns empty dict for empty registry."""
        result = _branches(tmp_path, {"plans": {}})
        assert result == {}

    def test_missing_plans_key(self, tmp_path, mock_logger):
        """Returns empty dict when registry has no plans key — as a normal registry, not a failure.

        Mutant: `data.get("plans", {})` -> `data["plans"]` reddens this.
        """
        ok, written = _push(tmp_path, {"fplan_registry.json": {"next_number": 3}})
        assert ok is True
        assert written["branches"] == {}
        mock_logger.warning.assert_not_called()

    def test_skips_plans_without_location(self, tmp_path):
        """Plans with empty location are skipped."""
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "No location",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/p/FPLAN-0001.md",
                    "location": "",
                },
            }
        }
        result = _branches(tmp_path, registry)
        assert result == {}

    def test_branch_section_structure(self, tmp_path):
        """Each branch section has required keys."""
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Structured",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/p/FPLAN-0001.md",
                    "relative_path": "FPLAN-0001.md",
                    "location": "/repo/src/aipass/flow",
                },
            }
        }
        result = _branches(tmp_path, registry)
        section = result["flow"]
        assert section["branch_name"] == "FLOW"
        assert section["branch_path"] == "/repo/src/aipass/flow"
        assert "active_plans" in section
        assert "recently_closed" in section
        assert "statistics" in section
        entry = section["active_plans"][0]
        assert "plan_id" in entry
        assert "subject" in entry
        assert "branch" in entry

    def test_plan_entries_have_branch_field(self, tmp_path):
        """Each plan entry includes the branch field."""
        registry = {
            "plans": {
                "DPLAN-0001": {
                    "subject": "Test",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/p/DPLAN-0001.md",
                    "location": "/repo/src/aipass/devpulse",
                },
            }
        }
        result = _branches(tmp_path, registry)
        assert result["devpulse"]["active_plans"][0]["branch"] == "devpulse"


# =============================================
# 5. _load_central
# =============================================


class TestLoadCentral:
    """Tests for _load_central."""

    def test_returns_empty_structure_when_file_missing(self, tmp_path, mock_logger):
        """A missing PLANS.central.json is started from the empty structure — silently.

        Mutant: `if not CENTRAL_FILE.exists():` -> `if False:` reddens this.
        """
        result, written = _push(tmp_path)

        assert result is True
        mock_logger.warning.assert_not_called()
        assert set(written) == {"generated_at", "branches", "global_statistics"}
        assert written["branches"] == {}
        assert written["global_statistics"] == {"total_active": 0, "total_closed": 0, "branches_reporting": 0}

    def test_loads_existing_central_file(self, tmp_path):
        """An existing PLANS.central.json is loaded, and what the push does not own survives.

        Mutant: `return json.load(f)` -> `return {}` reddens this.
        """
        central_data = {
            "generated_at": "2026-04-20T00:00:00Z",
            "branches": {"flow": {"branch_name": "FLOW"}},
            "global_statistics": {"total_active": 5, "total_closed": 10, "branches_reporting": 2},
            "active_plans": ["kept by aggregate"],
        }

        result, written = _push(tmp_path, central=central_data)

        assert result is True
        assert written["active_plans"] == ["kept by aggregate"]
        assert written["generated_at"] != "2026-04-20T00:00:00Z"
        assert written["branches"] == {}

    def test_returns_empty_structure_on_corrupt_json(self, tmp_path):
        """A corrupt PLANS.central.json is replaced, not fatal."""
        result, written = _push(tmp_path, central=b"not valid json!!!")

        assert result is True
        assert set(written) == {"generated_at", "branches", "global_statistics"}

    def test_returns_empty_structure_on_read_exception(self, tmp_path):
        """A central file that cannot even be DECODED is replaced, not fatal.

        The unreadable file is real bytes on disk (invalid UTF-8), so the read
        raises in the product itself — no patch over ``open``.
        Mutant: the load's `except Exception` -> `except json.JSONDecodeError` reddens this.
        """
        result, written = _push(tmp_path, central=b"\xff\xfe\x00 not utf-8")

        assert result is True
        assert set(written) == {"generated_at", "branches", "global_statistics"}


# =============================================
# 6. _calculate_global_statistics
# =============================================


class TestCalculateGlobalStatistics:
    """Tests for _calculate_global_statistics."""

    def test_sums_across_branches(self, tmp_path):
        """Sums active and closed counts across all branches.

        Mutant: `total_closed += ...` -> `total_closed = ...` reddens this.
        """
        plans = {}
        n = 0
        for branch, active, closed in (("flow", 3, 5), ("drone", 2, 8), ("prax", 1, 2)):
            for status, count in (("open", active), ("closed", closed)):
                for _ in range(count):
                    n += 1
                    plans[str(n)] = _row("FPLAN", n, branch, status=status)
        result, written = _push(tmp_path, {"fplan_registry.json": {"plans": plans}})

        stats = written["global_statistics"]
        assert stats["total_active"] == 6
        assert stats["total_closed"] == 15
        assert stats["branches_reporting"] == 3

    def test_empty_branches(self, tmp_path):
        """Returns zeros for empty branches dict — stale totals do not survive."""
        stale = {"branches": {}, "global_statistics": {"total_active": 9, "total_closed": 9, "branches_reporting": 9}}
        result, written = _push(tmp_path, {"fplan_registry.json": {"plans": {}}}, central=stale)
        assert written["global_statistics"] == {"total_active": 0, "total_closed": 0, "branches_reporting": 0}

    def test_no_branches_key(self, tmp_path):
        """Returns zeros when the existing central file has no branches key."""
        result, written = _push(tmp_path, central={"generated_at": ""})
        assert written["global_statistics"] == {"total_active": 0, "total_closed": 0, "branches_reporting": 0}

    def test_branch_missing_statistics(self):
        """Handles branches without statistics key."""
        central_data = {
            "branches": {
                "flow": {"statistics": {"active_count": 3, "total_closed": 5}},
                "broken": {},
            }
        }
        result = mod._calculate_global_statistics(central_data)
        assert result["total_active"] == 3
        assert result["total_closed"] == 5
        assert result["branches_reporting"] == 2

    def test_single_branch(self, tmp_path):
        """Handles a single branch correctly."""
        plans = {str(n): _row("FPLAN", n, "flow", status="open" if n <= 7 else "closed") for n in range(1, 20)}
        result, written = _push(tmp_path, {"fplan_registry.json": {"plans": plans}})
        stats = written["global_statistics"]
        assert stats["total_active"] == 7
        assert stats["total_closed"] == 12
        assert stats["branches_reporting"] == 1


# =============================================
# 7. push_to_plans_central
# =============================================


class TestPushToPlansCentral:
    """Tests for push_to_plans_central main handler."""

    def test_success_returns_true(self, tmp_path, mock_json_handler):
        """Returns True on successful push."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_branches = {
            "flow": {
                "branch_name": "FLOW",
                "branch_path": str(mod.FLOW_ROOT),
                "active_plans": [{"plan_id": "FPLAN-0001", "subject": "Test", "status": "open"}],
                "recently_closed": [],
                "statistics": {"active_count": 1, "total_closed": 0, "recently_closed_included": 0},
            }
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_extract_plans_by_branch", return_value=mock_branches),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        assert result is True
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        mock_json_handler.assert_called_once()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "plans_central_pushed"
        assert call_args[0][1]["success"] is True
        assert call_args[0][1]["active_plans"] == 1

    def test_writes_central_file(self, tmp_path):
        """Writes PLANS.central.json with correct structure."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        assert central_file.exists()
        written = json.loads(central_file.read_text(encoding="utf-8"))
        assert "branches" in written
        assert "global_statistics" in written
        assert "generated_at" in written
        assert written["generated_at"] != ""

    def test_writes_multiple_branches(self, tmp_path):
        """Writes per-branch sections from registry data."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_branches = {
            "flow": {
                "branch_name": "FLOW",
                "branch_path": "/repo/src/aipass/flow",
                "active_plans": [],
                "recently_closed": [],
                "statistics": {"active_count": 0, "total_closed": 0, "recently_closed_included": 0},
            },
            "devpulse": {
                "branch_name": "DEVPULSE",
                "branch_path": "/repo/src/aipass/devpulse",
                "active_plans": [{"plan_id": "DPLAN-0001"}],
                "recently_closed": [],
                "statistics": {"active_count": 1, "total_closed": 0, "recently_closed_included": 0},
            },
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_extract_plans_by_branch", return_value=mock_branches),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        written = json.loads(central_file.read_text(encoding="utf-8"))
        assert "flow" in written["branches"]
        assert "devpulse" in written["branches"]

    def test_creates_ai_central_dir(self, tmp_path):
        """Creates .ai_central directory if it does not exist."""
        ai_central = tmp_path / "new_ai_central"
        central_file = ai_central / "PLANS.central.json"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        assert ai_central.exists()

    def test_returns_false_on_exception(self, tmp_path):
        """Returns False when an exception occurs."""
        with (
            patch.object(mod, "AI_CENTRAL_DIR", tmp_path / ".ai_central"),
            patch.object(mod, "_load_registry", side_effect=RuntimeError("registry exploded")),
        ):
            result = mod.push_to_plans_central()

        assert result is False

    def test_branch_section_has_correct_statistics(self, tmp_path):
        """Branch section statistics reflect actual plan counts."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 4}
        mock_branches = {
            "flow": {
                "branch_name": "FLOW",
                "branch_path": str(mod.FLOW_ROOT),
                "active_plans": [
                    {"plan_id": "FPLAN-0001", "status": "open"},
                    {"plan_id": "FPLAN-0002", "status": "open"},
                ],
                "recently_closed": [{"plan_id": "FPLAN-0003", "status": "closed"}],
                "statistics": {"active_count": 2, "total_closed": 1, "recently_closed_included": 1},
            }
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_extract_plans_by_branch", return_value=mock_branches),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        written = json.loads(central_file.read_text(encoding="utf-8"))
        flow = written["branches"]["flow"]
        assert flow["statistics"]["active_count"] == 2
        assert flow["statistics"]["total_closed"] == 1
        assert flow["branch_name"] == "FLOW"

    def test_global_statistics_updated(self, tmp_path):
        """Global statistics are recalculated from all branch sections."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_branches = {
            "flow": {
                "branch_name": "FLOW",
                "branch_path": str(mod.FLOW_ROOT),
                "active_plans": [],
                "recently_closed": [],
                "statistics": {"active_count": 0, "total_closed": 0, "recently_closed_included": 0},
            },
            "devpulse": {
                "branch_name": "DEVPULSE",
                "branch_path": "/repo/src/aipass/devpulse",
                "active_plans": [{"plan_id": "DPLAN-0001"}],
                "recently_closed": [],
                "statistics": {"active_count": 5, "total_closed": 3, "recently_closed_included": 0},
            },
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_extract_plans_by_branch", return_value=mock_branches),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        written = json.loads(central_file.read_text(encoding="utf-8"))
        stats = written["global_statistics"]
        assert stats["total_active"] == 5
        assert stats["total_closed"] == 3
        assert stats["branches_reporting"] == 2

    def test_log_operation_contains_expected_fields(self, tmp_path, mock_json_handler):
        """Log operation includes active_plans and branches_reporting."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {"plans": {}, "next_number": 1}
        mock_branches = {
            "flow": {
                "branch_name": "FLOW",
                "branch_path": str(mod.FLOW_ROOT),
                "active_plans": [{"plan_id": "FPLAN-0001"}],
                "recently_closed": [],
                "statistics": {"active_count": 1, "total_closed": 0, "recently_closed_included": 0},
            },
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_extract_plans_by_branch", return_value=mock_branches),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)

        call_args = mock_json_handler.call_args
        log_data = call_args[0][1]
        assert log_data["active_plans"] == 1
        assert "branches_reporting" in log_data

    def test_non_flow_branch_plans_in_central(self, tmp_path):
        """Regression: non-flow branch plans must appear in PLANS.central.json."""
        central_file = tmp_path / "PLANS.central.json"
        ai_central = tmp_path / ".ai_central"

        mock_registry = {
            "plans": {
                "DPLAN-0181": {
                    "subject": "Devpulse plan",
                    "status": "open",
                    "created": "2026-05-01",
                    "file_path": "/repo/src/aipass/devpulse/DPLAN-0181.md",
                    "location": "/repo/src/aipass/devpulse",
                },
                "FPLAN-0001": {
                    "subject": "Flow plan",
                    "status": "open",
                    "created": "2026-05-02",
                    "file_path": "/repo/src/aipass/flow/FPLAN-0001.md",
                    "location": str(mod.FLOW_ROOT),
                },
            },
            "next_number": 1,
        }
        mock_central = {
            "generated_at": "",
            "branches": {},
            "global_statistics": {"total_active": 0, "total_closed": 0, "branches_reporting": 0},
        }

        with (
            patch.object(mod, "AI_CENTRAL_DIR", ai_central),
            patch.object(mod, "CENTRAL_FILE", central_file),
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_load_central", return_value=mock_central),
            patch.object(mod, "aggregate_central_impl") as mock_agg,
        ):
            result = mod.push_to_plans_central()

        # Stays patched: with heal=True it auto-closes rows in live branch registries.
        mock_agg.assert_called_once_with(heal=True, central_file=central_file, central_dir=ai_central)
        assert result is True
        written = json.loads(central_file.read_text(encoding="utf-8"))
        assert "devpulse" in written["branches"]
        devpulse = written["branches"]["devpulse"]
        assert devpulse["statistics"]["active_count"] == 1
        assert len(devpulse["active_plans"]) == 1
        assert devpulse["active_plans"][0]["plan_id"] == "DPLAN-0181"
        assert devpulse["active_plans"][0]["branch"] == "devpulse"

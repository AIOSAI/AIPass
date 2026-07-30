# =================== AIPass ====================
# Name: test_heal_registry.py
# Description: Tests for heal_registry doctrine self-heal handler
# Version: 1.0.0
# Created: 2026-07-29
# Modified: 2026-07-29
# =============================================

"""Tests for the registry doctrine self-heal handler.

Covers the three corruption classes the doctrine must auto-fix:
1. Number collision  -> resolved_collision
2. Unregistered file -> registered_unregistered_file
3. Wrong-prefix row  -> removed_ghost_row / rehomed_wrong_prefix_row /
                        removed_orphaned_wrong_prefix_row

Invariant asserted throughout: on-disk .md files are NEVER renamed,
moved or deleted by this handler — only registry JSON rows change.
"""

import copy
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Import helpers ───────────────────────────────────────


def _import_heal_registry():
    """Import heal_registry handler module and return it."""
    import aipass.flow.apps.handlers.registry.heal_registry as mod

    return mod


# ─── Fake registry store (mimics load/save round-tripping to disk) ───


class FakeRegistryStore:
    """In-memory stand-in for flow_json/*.json registries.

    ``load``/``save`` deep-copy so callers cannot mutate stored state by
    reference — same isolation the real JSON file round-trip provides.
    """

    def __init__(self, registries=None):
        self.registries = copy.deepcopy(registries or {})
        self.saves = []

    def load(self, registry_file=None):
        """Return a detached copy of the named registry."""
        key = registry_file or "fplan_registry.json"
        return copy.deepcopy(self.registries.get(key, {"plans": {}, "next_number": 1}))

    def save(self, registry, registry_file=None):
        """Store a detached copy of the registry and record the write."""
        key = registry_file or "fplan_registry.json"
        self.registries[key] = copy.deepcopy(registry)
        self.saves.append(key)
        return True

    def plans(self, registry_file):
        """Return the stored plans dict for the named registry."""
        return self.registries.get(registry_file, {}).get("plans", {})


def _make_plan_file(directory: Path, name: str) -> Path:
    """Create a real plan .md file so the filesystem walk can find it."""
    directory.mkdir(parents=True, exist_ok=True)
    plan_file = directory / name
    plan_file.write_text(f"# {name}\nContent that must never be touched.\n", encoding="utf-8")
    return plan_file


@pytest.fixture
def quiet_cross_prefix():
    """Silence close_helpers' cross-prefix note lookup during self-heal."""
    with patch(
        "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
        return_value={"types": {}},
    ) as mock:
        yield mock


# ═══════════════════════════════════════════════════════════
# 1. _build_plan_file_index
# ═══════════════════════════════════════════════════════════


class TestBuildPlanFileIndex:
    """Tests for the (prefix, number) filesystem index."""

    def test_indexes_by_prefix_and_number(self, tmp_path):
        """Same number under different prefixes must stay separate entries."""
        mod = _import_heal_registry()
        _make_plan_file(tmp_path, "DPLAN-0011_alpha_2026-01-01.md")
        _make_plan_file(tmp_path / "sub", "TDPLAN-0011_beta_2026-01-02.md")
        _make_plan_file(tmp_path, "PPLAN-0011.md")

        index = mod._build_plan_file_index(tmp_path)

        assert ("DPLAN", "0011") in index
        assert ("TDPLAN", "0011") in index
        assert ("PPLAN", "0011") in index
        assert len(index) == 3

    def test_skips_ignored_folders_and_non_plan_files(self, tmp_path):
        """IGNORE_FOLDERS pruning and PLAN_PATTERN filtering both apply."""
        mod = _import_heal_registry()
        _make_plan_file(tmp_path / ".git", "FPLAN-0001.md")
        _make_plan_file(tmp_path / ".archive", "FPLAN-0002.md")
        _make_plan_file(tmp_path, "FPLAN-0003.md")
        (tmp_path / "README.md").write_text("not a plan", encoding="utf-8")
        (tmp_path / "FPLAN-ABC.md").write_text("bad number", encoding="utf-8")

        index = mod._build_plan_file_index(tmp_path)

        assert index == {("FPLAN", "0003"): tmp_path / "FPLAN-0003.md"}

    def test_missing_root_is_tolerated(self, tmp_path):
        """A nonexistent root yields an empty index, not an exception."""
        mod = _import_heal_registry()
        assert mod._build_plan_file_index(tmp_path / "nope") == {}


# ═══════════════════════════════════════════════════════════
# 2. Case 2 — unregistered file
# ═══════════════════════════════════════════════════════════


class TestUnregisteredFile:
    """A real plan file with no registry row gets registered."""

    def test_registers_under_own_number(self, tmp_path, quiet_cross_prefix):
        """A free number is claimed as-is, with self_healed marked True."""
        mod = _import_heal_registry()
        plan_file = _make_plan_file(tmp_path, "DPLAN-0042_new_thing_2026-07-01.md")
        store = FakeRegistryStore({"dplan_registry.json": {"plans": {}, "next_number": 40}})

        actions = mod._heal_type_registry(
            "DPLAN",
            "dplan_registry.json",
            {("DPLAN", "0042"): plan_file},
            store.load,
            store.save,
        )

        assert len(actions) == 1
        assert actions[0]["action"] == "registered_unregistered_file"
        assert actions[0]["number"] == "0042"
        assert actions[0]["file"] == str(plan_file)

        healed = store.plans("dplan_registry.json")["0042"]
        assert healed["self_healed"] is True
        assert healed["file_path"] == str(plan_file)
        # File itself is untouched — by design this handler never writes .md files.
        assert plan_file.exists()

    def test_other_type_files_are_ignored(self, tmp_path, quiet_cross_prefix):
        """Only files whose prefix matches this registry are considered."""
        mod = _import_heal_registry()
        tdplan_file = _make_plan_file(tmp_path, "TDPLAN-0007.md")
        store = FakeRegistryStore({"dplan_registry.json": {"plans": {}, "next_number": 1}})

        actions = mod._heal_type_registry(
            "DPLAN",
            "dplan_registry.json",
            {("TDPLAN", "0007"): tdplan_file},
            store.load,
            store.save,
        )

        assert actions == []
        assert store.saves == []

    def test_correctly_registered_file_is_left_alone(self, tmp_path, quiet_cross_prefix):
        """A row already pointing at the on-disk file needs no heal."""
        mod = _import_heal_registry()
        plan_file = _make_plan_file(tmp_path, "FPLAN-0100_ok_2026-05-05.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0100": {"status": "open", "file_path": str(plan_file)}},
                    "next_number": 101,
                }
            }
        )

        actions = mod._heal_type_registry(
            "FPLAN",
            "fplan_registry.json",
            {("FPLAN", "0100"): plan_file},
            store.load,
            store.save,
        )

        assert actions == []
        assert store.saves == []


# ═══════════════════════════════════════════════════════════
# 3. Case 1 — number collision
# ═══════════════════════════════════════════════════════════


class TestNumberCollision:
    """Ghost row + different real file on the same prefix+number."""

    def test_bumps_new_file_and_preserves_original_row(self, tmp_path, quiet_cross_prefix):
        """The on-disk file takes next_number; the ghost row survives intact."""
        mod = _import_heal_registry()
        real_file = _make_plan_file(tmp_path, "FPLAN-0011_real_plan_2026-07-01.md")
        ghost_row = {
            "status": "open",
            "subject": "ghost",
            "file_path": str(tmp_path / "gone" / "FPLAN-0011_ghost_2026-01-01.md"),
        }
        store = FakeRegistryStore(
            {"fplan_registry.json": {"plans": {"0011": copy.deepcopy(ghost_row)}, "next_number": 356}}
        )

        actions = mod._heal_type_registry(
            "FPLAN",
            "fplan_registry.json",
            {("FPLAN", "0011"): real_file},
            store.load,
            store.save,
        )

        assert len(actions) == 1
        assert actions[0]["action"] == "resolved_collision"
        assert actions[0]["number"] == "0356"

        plans = store.plans("fplan_registry.json")
        # Original (registry-of-record) row survives byte-for-byte.
        assert plans["0011"] == ghost_row
        assert plans["0356"]["file_path"] == str(real_file)
        assert plans["0356"]["self_healed"] is True
        assert store.registries["fplan_registry.json"]["next_number"] == 357
        # The on-disk file is never renamed or removed.
        assert real_file.exists()

    def test_relocated_old_row_is_still_a_collision(self, tmp_path, quiet_cross_prefix):
        """An old row's file being safely archived says nothing about whether the
        different, real, live file now squatting on its number is registered --
        it isn't, so it's still a collision needing its own fresh slot."""
        mod = _import_heal_registry()
        real_file = _make_plan_file(tmp_path, "FPLAN-0011_real_plan_2026-07-01.md")
        # The old row's own file really is archived elsewhere -- irrelevant to
        # whether `real_file` (a different plan) is registered under "0011".
        _make_plan_file(tmp_path / "elsewhere", "FPLAN-0011_ghost_2026-01-01.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {
                        "0011": {
                            "status": "open",
                            "file_path": str(tmp_path / "gone" / "FPLAN-0011_ghost_2026-01-01.md"),
                        }
                    },
                    "next_number": 356,
                }
            }
        )

        actions = mod._heal_type_registry(
            "FPLAN",
            "fplan_registry.json",
            {("FPLAN", "0011"): real_file},
            store.load,
            store.save,
        )

        assert len(actions) == 1
        assert actions[0]["action"] == "resolved_collision"
        assert store.plans("fplan_registry.json")["0011"]["status"] == "open"

    def test_closed_row_not_relocated_is_still_a_collision(self, tmp_path, quiet_cross_prefix):
        """Closed status alone doesn't excuse a stale path -- an unrelated live file
        squatting on the same number is a genuine collision regardless of status."""
        mod = _import_heal_registry()
        real_file = _make_plan_file(tmp_path, "DPLAN-0050_something_2026-07-01.md")
        store = FakeRegistryStore(
            {
                "dplan_registry.json": {
                    "plans": {
                        "0050": {
                            "status": "closed",
                            "file_path": str(tmp_path / "gone" / "DPLAN-0050_old_2026-01-01.md"),
                        }
                    },
                    "next_number": 60,
                }
            }
        )

        actions = mod._heal_type_registry(
            "DPLAN",
            "dplan_registry.json",
            {("DPLAN", "0050"): real_file},
            store.load,
            store.save,
        )

        assert len(actions) == 1
        assert actions[0]["action"] == "resolved_collision"
        assert store.plans("dplan_registry.json")["0050"]["status"] == "closed"

    def test_existing_registered_path_is_left_alone(self, tmp_path, quiet_cross_prefix):
        """Two real files, one registered — not a doctrine case, hands off."""
        mod = _import_heal_registry()
        registered = _make_plan_file(tmp_path / "a", "FPLAN-0012_one_2026-07-01.md")
        other = _make_plan_file(tmp_path / "b", "FPLAN-0012_two_2026-07-02.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0012": {"status": "open", "file_path": str(registered)}},
                    "next_number": 20,
                }
            }
        )

        actions = mod._heal_type_registry(
            "FPLAN",
            "fplan_registry.json",
            {("FPLAN", "0012"): other},
            store.load,
            store.save,
        )

        assert actions == []
        assert store.saves == []

    def test_second_scan_of_same_collision_heals_nothing(self, tmp_path, quiet_cross_prefix):
        """Idempotency: the squatter keeps its OLD number in its filename forever, so a
        second scan must not mint a second fresh row for the file it already resolved
        on the first pass (the exact non-idempotency bug @devpulse caught live)."""
        mod = _import_heal_registry()
        real_file = _make_plan_file(tmp_path, "DPLAN-0165_compass_wiring_2026-05-04.md")
        store = FakeRegistryStore(
            {
                "dplan_registry.json": {
                    "plans": {
                        "0165": {
                            "status": "open",
                            "file_path": str(tmp_path / "gone" / "DPLAN-0165_old_2026-01-01.md"),
                        }
                    },
                    "next_number": 265,
                }
            }
        )
        on_disk_index = {("DPLAN", "0165"): real_file}

        first_actions = mod._heal_type_registry("DPLAN", "dplan_registry.json", on_disk_index, store.load, store.save)
        assert len(first_actions) == 1
        assert first_actions[0]["action"] == "resolved_collision"
        assert first_actions[0]["number"] == "0265"

        second_actions = mod._heal_type_registry("DPLAN", "dplan_registry.json", on_disk_index, store.load, store.save)
        assert second_actions == []

        plans = store.plans("dplan_registry.json")
        assert plans["0165"]["status"] == "open"  # original row still untouched
        assert plans["0265"]["file_path"] == str(real_file)
        assert "0267" not in plans  # no second-generation duplicate minted

    def test_row_without_file_path_is_left_alone(self, tmp_path, quiet_cross_prefix):
        """No file_path means nothing deterministic to compare — skip."""
        mod = _import_heal_registry()
        real_file = _make_plan_file(tmp_path, "FPLAN-0013_thing_2026-07-01.md")
        store = FakeRegistryStore({"fplan_registry.json": {"plans": {"0013": {"status": "open"}}, "next_number": 20}})

        actions = mod._heal_type_registry(
            "FPLAN",
            "fplan_registry.json",
            {("FPLAN", "0013"): real_file},
            store.load,
            store.save,
        )

        assert actions == []
        assert store.saves == []


# ═══════════════════════════════════════════════════════════
# 4. Case 3 — wrong-prefix rows
# ═══════════════════════════════════════════════════════════


TYPES = {
    "flow_plans": {"prefix": "FPLAN"},
    "team_dev_plans": {"prefix": "TDPLAN"},
}


class TestWrongPrefixRows:
    """Rows sitting in the wrong type registry get removed or re-homed."""

    def test_ghost_duplicate_row_is_removed(self, tmp_path, quiet_cross_prefix):
        """The real FPLAN-0011 audit finding: ghost row, real plan already correct."""
        mod = _import_heal_registry()
        tdplan_file = tmp_path / "TDPLAN-0011_team_thing_2026-04-10.md"
        correct_row = {"status": "closed", "subject": "team thing", "file_path": str(tdplan_file)}
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {
                        "0011": {"status": "open", "subject": "ghost", "file_path": str(tdplan_file)},
                        "0020": {"status": "open", "file_path": str(tmp_path / "FPLAN-0020.md")},
                    },
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {"0011": copy.deepcopy(correct_row)}, "next_number": 15},
            }
        )

        actions = mod._heal_wrong_prefix_rows(TYPES, store.load, store.save)

        assert len(actions) == 1
        assert actions[0]["action"] == "removed_ghost_row"
        assert actions[0]["prefix_found"] == "TDPLAN"
        assert actions[0]["number"] == "0011"
        assert actions[0]["wrong_registry_file"] == "fplan_registry.json"

        assert "0011" not in store.plans("fplan_registry.json")
        assert "0020" in store.plans("fplan_registry.json")
        # Correct registry untouched.
        assert store.registries["tdplan_registry.json"]["plans"] == {"0011": correct_row}
        assert store.registries["tdplan_registry.json"]["next_number"] == 15

    def test_real_file_is_rehomed_to_correct_registry(self, tmp_path, quiet_cross_prefix):
        """A real file behind a wrong-prefix row moves to its own registry."""
        mod = _import_heal_registry()
        tdplan_file = _make_plan_file(tmp_path, "TDPLAN-0009_real_team_plan_2026-06-01.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0009": {"status": "open", "file_path": str(tdplan_file)}},
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        actions = mod._heal_wrong_prefix_rows(TYPES, store.load, store.save)

        assert len(actions) == 1
        assert actions[0]["action"] == "rehomed_wrong_prefix_row"
        assert "0009" not in store.plans("fplan_registry.json")

        rehomed = store.plans("tdplan_registry.json")["0009"]
        assert rehomed["file_path"] == str(tdplan_file)
        assert rehomed["self_healed"] is True
        # File itself never moved.
        assert tdplan_file.exists()

    def test_orphaned_metadata_row_is_removed(self, tmp_path, quiet_cross_prefix):
        """No file anywhere and no correct registration — drop the dead row."""
        mod = _import_heal_registry()
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {
                        "0030": {
                            "status": "open",
                            "file_path": str(tmp_path / "gone" / "TDPLAN-0030_vanished_2026-02-02.md"),
                        }
                    },
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        actions = mod._heal_wrong_prefix_rows(TYPES, store.load, store.save)

        assert len(actions) == 1
        assert actions[0]["action"] == "removed_orphaned_wrong_prefix_row"
        assert store.plans("fplan_registry.json") == {}
        assert store.plans("tdplan_registry.json") == {}

    def test_unknown_prefix_is_left_alone(self, tmp_path, quiet_cross_prefix):
        """Unregistered prefixes are never guessed at."""
        mod = _import_heal_registry()
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0040": {"status": "open", "file_path": str(tmp_path / "XPLAN-0040_weird.md")}},
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        actions = mod._heal_wrong_prefix_rows(TYPES, store.load, store.save)

        assert actions == []
        assert "0040" in store.plans("fplan_registry.json")

    def test_matching_prefix_rows_are_untouched(self, tmp_path, quiet_cross_prefix):
        """Rows whose file_path prefix matches their host registry are fine."""
        mod = _import_heal_registry()
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0050": {"status": "open", "file_path": str(tmp_path / "FPLAN-0050_fine.md")}},
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        actions = mod._heal_wrong_prefix_rows(TYPES, store.load, store.save)

        assert actions == []
        assert store.saves == []


# ═══════════════════════════════════════════════════════════
# 5. heal_registry_doctrine_impl — orchestrator
# ═══════════════════════════════════════════════════════════


class TestHealRegistryDoctrineImpl:
    """End-to-end orchestration across all registered types."""

    def test_returns_summary_shape_and_logs_operation(self, tmp_path, quiet_cross_prefix, mock_json_handler):
        """healed_count matches len(healed) and the op is logged once."""
        mod = _import_heal_registry()
        _make_plan_file(tmp_path, "TDPLAN-0003_fresh_plan_2026-07-01.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {"plans": {}, "next_number": 356},
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        with patch.object(mod, "_load_template_registry", return_value={"types": TYPES}):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        assert set(result) == {"healed", "healed_count"}
        assert result["healed_count"] == len(result["healed"]) == 1
        assert result["healed"][0]["action"] == "registered_unregistered_file"

        logged = [c for c in mock_json_handler.call_args_list if c.args and c.args[0] == "registry_doctrine_heal"]
        assert len(logged) == 1
        assert logged[0].args[1]["total_heals"] == 1
        assert logged[0].args[1]["by_action"] == {"registered_unregistered_file": 1}

    def test_healthy_registry_produces_no_actions(self, tmp_path, quiet_cross_prefix):
        """A consistent registry is never written to."""
        mod = _import_heal_registry()
        plan_file = _make_plan_file(tmp_path, "FPLAN-0200_all_good_2026-07-01.md")
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {"0200": {"status": "open", "file_path": str(plan_file)}},
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        with patch.object(mod, "_load_template_registry", return_value={"types": TYPES}):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        assert result == {"healed": [], "healed_count": 0}
        assert store.saves == []

    def test_per_type_heals_run_before_wrong_prefix_sweep(self, tmp_path, quiet_cross_prefix):
        """Case 1/2 first, then case 3 — so case 3 is left with ghost cleanup only."""
        mod = _import_heal_registry()
        tdplan_file = _make_plan_file(tmp_path, "TDPLAN-0011_team_thing_2026-04-10.md")
        store = FakeRegistryStore(
            {
                # Ghost FPLAN row pointing at the TDPLAN file (the real audit finding)
                "fplan_registry.json": {
                    "plans": {"0011": {"status": "open", "file_path": str(tdplan_file)}},
                    "next_number": 356,
                },
                # TDPLAN-0011 not yet registered anywhere correct
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        with patch.object(mod, "_load_template_registry", return_value={"types": TYPES}):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        performed = [a["action"] for a in result["healed"]]
        assert performed == ["registered_unregistered_file", "removed_ghost_row"]

        # TDPLAN registry now owns the plan, FPLAN ghost row is gone.
        assert store.plans("tdplan_registry.json")["0011"]["file_path"] == str(tdplan_file)
        assert store.plans("fplan_registry.json") == {}
        # And the .md file was never renamed or deleted.
        assert tdplan_file.exists()
        assert tdplan_file.read_text(encoding="utf-8").startswith("# TDPLAN-0011")

    def test_types_without_prefix_are_skipped(self, tmp_path, quiet_cross_prefix):
        """A malformed template-registry type entry cannot crash the sweep."""
        mod = _import_heal_registry()
        store = FakeRegistryStore({})

        with patch.object(mod, "_load_template_registry", return_value={"types": {"broken": {}}}):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        assert result["healed_count"] == 0

    def test_type_heal_failure_does_not_abort_run(self, tmp_path, quiet_cross_prefix):
        """A blown-up type is logged and the sweep still completes."""
        mod = _import_heal_registry()
        store = FakeRegistryStore(
            {
                "fplan_registry.json": {"plans": {}, "next_number": 1},
                "tdplan_registry.json": {"plans": {}, "next_number": 1},
            }
        )

        with (
            patch.object(mod, "_load_template_registry", return_value={"types": TYPES}),
            patch.object(mod, "_heal_type_registry", side_effect=RuntimeError("boom")),
        ):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        assert result == {"healed": [], "healed_count": 0}


# ═══════════════════════════════════════════════════════════
# 6. Files are never mutated
# ═══════════════════════════════════════════════════════════


class TestNeverTouchesPlanFiles:
    """Hard doctrine guarantee: registry rows change, .md files never do."""

    def test_no_rename_or_unlink_during_full_heal(self, tmp_path, quiet_cross_prefix):
        """Any rename/unlink/write_text on a Path during a heal is a failure."""
        mod = _import_heal_registry()
        collided = _make_plan_file(tmp_path, "FPLAN-0011_real_2026-07-01.md")
        unregistered = _make_plan_file(tmp_path, "TDPLAN-0009_new_2026-07-02.md")
        before = {p: p.read_text(encoding="utf-8") for p in (collided, unregistered)}

        store = FakeRegistryStore(
            {
                "fplan_registry.json": {
                    "plans": {
                        "0011": {"status": "open", "file_path": str(tmp_path / "gone" / "FPLAN-0011_ghost.md")},
                    },
                    "next_number": 356,
                },
                "tdplan_registry.json": {"plans": {}, "next_number": 15},
            }
        )

        with (
            patch.object(mod, "_load_template_registry", return_value={"types": TYPES}),
            patch.object(Path, "rename", side_effect=AssertionError("plan files must never be renamed")),
            patch.object(Path, "unlink", side_effect=AssertionError("plan files must never be deleted")),
            patch.object(Path, "write_text", side_effect=AssertionError("plan files must never be rewritten")),
        ):
            result = mod.heal_registry_doctrine_impl(tmp_path, store.load, store.save)

        assert result["healed_count"] == 2
        for path, content in before.items():
            assert path.exists()
            assert path.read_text(encoding="utf-8") == content

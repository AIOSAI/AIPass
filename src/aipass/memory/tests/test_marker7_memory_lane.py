# =================== AIPass ====================
# Name: test_marker7_memory_lane.py
# Description: Red-first pins for marker 7 — self-healing triggers and the aftercare rulings
# Version: 1.2.2
# Created: 2026-08-27
# Modified: 2026-10-23
# =============================================

"""Tests for apps/modules/rollover.py, apps/modules/templates.py and the handlers they drive."""

# Self-healing is TRIGGER-DRIVEN, never a daemon: a lane heals because something happened.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — rollover.show_status(), driven by tests/test_rollover_pipeline.py
# seedgo: no-test-needed(covered_elsewhere) — trinity_push.build_frame(), the push's write; tests/test_trinity_push.py

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest
from _pytest.outcomes import Skipped  # what pytest.skip() raises — caught here, never raised
from unittest.mock import MagicMock, patch

# MODULE level on purpose: conftest swaps `handlers.json` for a MagicMock package inside each test.
from aipass.cli.apps.modules import reset_command_state, resolve_exit
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.templates import trinity_push
from aipass.memory.apps.handlers.templates import template_bump
from aipass.memory.apps.handlers.rollover import normalizer
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json import entry_limits
from aipass.memory.apps.handlers.json import memory_files
from aipass.memory.apps.handlers import write_fence
from aipass.memory.apps.handlers.templates import spawn_pusher
from aipass.memory.apps.modules import rollover
from aipass.memory.apps.modules import templates

# Judged by the parts BELOW the walk's root: a checkout under a directory named dropbox must not hide itself.
_SKIPPED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _walk(root: Path, pattern: str = "*.py") -> list[Path]:
    """Every file under *root* matching *pattern*, outside the skipped directories."""
    return sorted(path for path in root.rglob(pattern) if not _SKIPPED_DIRS.intersection(path.relative_to(root).parts))


def test_the_walk_skips_dropbox_archive_and_caches_below_its_root_only(tmp_path: Path) -> None:
    """Red first against a bare rglob. The root stands inside a directory named dropbox; live/ is the control."""
    root = tmp_path / "dropbox" / "checkout"
    for name in (*sorted(_SKIPPED_DIRS), "live"):
        (root / name).mkdir(parents=True)
        (root / name / "test_x.py").write_text("", encoding="utf-8")
    assert _walk(root) == [root / "live" / "test_x.py"]


_MEMORY_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _MEMORY_ROOT.parents[2]


# =============================================================================
# ITEM 7 — ONE FLEET, ONE DEFINITION
# =============================================================================


class TestOneFleetOneDefinition:
    """Every @memory lane answers "which branches?" from the same source."""

    def test_the_fleet_reaches_all_four_resident_projects(self, live_residents):
        """Asks the resolver, not a literal: the resolver is the thing that has to be right."""
        names = {item["name"] for item in registry_scope.fleet_branches(live_residents)}
        assert {"baud", "earmark", "finch", "aipass_site"} <= names

    def test_a_held_project_is_never_swept_in(self, live_fleet):
        """marketstand marks its branch active INSIDE a directory named (on _hold).

        Guarded: with no registry the scope is empty and the assertion would measure nothing.
        """
        names = [item["name"] for item in registry_scope.fleet_branches()]
        assert "marketstand" not in names
        assert not any("hold" in name for name in names)

    def test_the_shared_scope_reaches_every_resident(self, live_residents):
        """Guarded on the RESIDENT FILES, not just on "aipass is installed" (a wheel install has none)."""
        names = {item["name"] for item in registry_scope.fleet_branches()}
        assert {"earmark", "finch", "aipass_site", "baud"} <= names

    def test_the_push_and_the_registry_lane_agree_on_the_fleet(self, live_fleet):
        """The push and the registry lane must agree on the fleet; guarded, as two empty sets agree on nothing."""
        push_names = {item["name"].lower() for item in trinity_push.resolve_scope()["branches"]}
        registry_names = {Path(item["path"]).name.lower() for item in detector._read_registry()}
        assert push_names <= registry_names, f"invisible to rollover/lint/health: {push_names - registry_names}"

    def test_the_push_never_reaches_into_another_repository(self, live_fleet):
        """The template push WRITES. So its scope stops at this repo's edge, external tier excluded."""
        scoped = trinity_push.resolve_scope()["branches"]
        assert scoped, "empty scope proves nothing about what it excludes"
        outsiders = [item for item in scoped if item.get("residency") == registry_scope.RESIDENCY_EXTERNAL]
        assert not outsiders, f"the push would write into another repository: {[i['name'] for i in outsiders]}"
        assert all(str(item["path"]).startswith(str(registry_scope.REPO_ROOT)) for item in scoped)

    def test_every_fleet_record_carries_exactly_the_five_agreed_keys(self, live_all_tiers):
        """The whole record shape, across ALL THREE TIERS, not just externals.

        A test that needs three tiers is guarded on three tiers (`live_all_tiers`).
        """
        rows = registry_scope.fleet_branches(live_all_tiers)
        assert rows, "an empty fleet proves nothing about record shape"
        tiers = {row["residency"] for row in rows}
        assert tiers == {
            registry_scope.RESIDENCY_CORE,
            registry_scope.RESIDENCY_RESIDENT,
            registry_scope.RESIDENCY_EXTERNAL,
        }, f"all three tiers must be exercised, got {tiers}"
        for row in rows:
            assert set(row) == {"name", "path", "registry", "email", "residency"}, row

    def test_the_normalize_lane_never_reaches_into_another_repository(self, live_fleet, monkeypatch):
        """The normalize lane writes, so it never reaches into another repository.

        Rolled branches are matched by name; an external branch sharing a name must never be rewritten.
        """
        seen = []
        monkeypatch.setattr(
            normalizer,
            "normalize_branch",
            lambda name, path, config: seen.append((name, Path(path))) or {"success": True},
        )
        fleet = registry_scope.fleet_branches()
        every_name = [item["name"] for item in fleet]
        in_repo = {item["name"] for item in fleet if item.get("residency") != registry_scope.RESIDENCY_EXTERNAL}
        rollover._normalize_rolled(every_name)

        assert {name for name, _ in seen} == in_repo, "every in-repo citizen that rolled heals, and nobody else"
        home = registry_scope.REPO_ROOT.resolve()
        outside = [p for _, p in seen if home not in p.resolve().parents and p.resolve() != home]
        assert not outside, f"normalize would write outside this repo: {outside}"

    def test_a_branch_whose_frame_could_not_be_written_is_named(self, live_fleet, monkeypatch, caplog):
        """The normalizer reports failure by return value; the caller must name the branch, not drop it.

        Guarded on `live_fleet`: with no registry @memory is out of scope and the other warning fires.
        """
        monkeypatch.setattr(
            normalizer,
            "normalize_branch",
            lambda name, path, config: {"success": False, "error": f"{name}: local.json write failed"},
        )
        # Captured at the logger, not via caplog: prax's logger does not always propagate to the root.
        said = []
        monkeypatch.setattr(rollover.logger, "warning", lambda msg, *a, **k: said.append(str(msg)))

        rollover._normalize_rolled(["memory"])

        joined = " ".join(said)
        assert "memory" in joined, joined
        assert "write failed" in joined, joined

    def test_the_rollover_lane_never_reaches_into_another_repository(self, live_fleet):
        """Rollover WRITES too — it trims memory files. Same edge as the push.

        Trap: repointing the detector at `fleet_branches` would pull the external tier into a write scope.
        """
        rolled = {Path(item["path"]).resolve() for item in detector._read_registry()}
        assert _MEMORY_ROOT.resolve() in rolled, "a scope without this branch proves nothing about what it excludes"
        home = registry_scope.REPO_ROOT.resolve()
        outside = [p for p in rolled if home not in p.parents and p != home]
        assert outside == [], f"rollover would write outside this repo: {outside}"

    # The write fence: memory may READ another project, never WRITE one, refused at the write itself.

    @staticmethod
    def _fenced_world(tmp_path, monkeypatch):
        """A fake AIPass root and a foreign project beside it, with the fence on the first."""
        home = tmp_path / "aipass"
        home.mkdir()
        monkeypatch.setattr(write_fence, "ROOT", home)
        foreign = tmp_path / "other_root" / "src" / "x" / ".trinity" / "local.json"
        foreign.parent.mkdir(parents=True)
        foreign.write_text('{\n  "sessions": []\n}\n', encoding="utf-8")
        return home, foreign

    def test_a_write_into_another_root_is_refused_and_the_file_is_untouched(self, tmp_path, monkeypatch):
        """The minimum pin: the gate most .trinity writers share says no, and means it.

        Refused: a failure result, foreign bytes unchanged, no temp file, an ERROR naming path and root.
        """
        home, foreign = self._fenced_world(tmp_path, monkeypatch)
        before = foreign.read_bytes()
        said = MagicMock()
        monkeypatch.setattr(write_fence, "logger", said)

        result = memory_files.write_memory_file(foreign, {"sessions": [{"number": 1, "summary": "rewritten"}]})

        assert result["success"] is False
        assert memory_files.write_memory_file_simple(foreign, {"sessions": []}) is False
        assert foreign.read_bytes() == before
        assert sorted(p.name for p in foreign.parent.iterdir()) == ["local.json"], "a temp file was left behind"
        # The rendered messages, never str(call): a call's repr doubles every Windows backslash.
        errors = " ".join(str(arg) for call in said.error.call_args_list for arg in call.args)
        assert str(foreign.resolve()) in errors and str(home.resolve()) in errors, errors

    def test_a_refused_write_is_recorded_in_the_operation_log(self, tmp_path, monkeypatch):
        """A refusal only the console saw is gone the moment the console is."""
        _home, foreign = self._fenced_world(tmp_path, monkeypatch)
        recorder = sys.modules["aipass.memory.apps.handlers.json.json_handler"]

        memory_files.write_memory_file(foreign, {"sessions": []})

        recorded = [call for call in recorder.log_operation.call_args_list if call.args[0] == "write_fence_refused"]
        assert recorded, recorder.log_operation.call_args_list
        assert recorded[0].args[1]["path"] == str(foreign.resolve())

    def test_a_write_inside_the_root_still_succeeds(self, tmp_path, monkeypatch):
        """Positive control. A fence that refuses everything also passes the pin above."""
        home, _foreign = self._fenced_world(tmp_path, monkeypatch)
        inside = home / "src" / "x" / ".trinity" / "local.json"
        inside.parent.mkdir(parents=True)

        result = memory_files.write_memory_file(inside, {"sessions": []})

        assert result["success"] is True, result
        assert json.loads(inside.read_text(encoding="utf-8")) == {"sessions": []}

    def test_a_symlink_inside_the_root_does_not_carry_a_write_out_of_it(self, tmp_path, monkeypatch):
        """The fence judges where the bytes LAND, not how the path is spelled."""
        home, foreign = self._fenced_world(tmp_path, monkeypatch)
        before = foreign.read_bytes()
        door = home / "src" / "door"
        door.parent.mkdir(parents=True)
        try:
            door.symlink_to(foreign.parent.parent, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"this filesystem cannot make a symlink ({exc}) -- nothing to pin")

        result = memory_files.write_memory_file(door / ".trinity" / "local.json", {"sessions": []})

        assert result["success"] is False
        assert foreign.read_bytes() == before

    def test_the_verdict_is_containment_not_a_shared_prefix(self, tmp_path):
        """The pure predicate, alone: ``/x/aipass_other`` is not inside ``/x/aipass``.

        A string ``startswith`` passes that sibling: fine for a measurement, wrong for a gate.
        """
        root = tmp_path / "aipass"

        assert write_fence.outside_root(root, root) is None
        assert write_fence.outside_root(root / "src" / "x" / ".trinity" / "local.json", root) is None
        sibling = write_fence.outside_root(tmp_path / "aipass_other" / "x", root)
        assert sibling is not None and str(tmp_path / "aipass_other" / "x") in sibling and str(root) in sibling
        assert write_fence.outside_root(tmp_path, root) is not None

    def test_a_filesystem_root_anchor_admits_nothing(self, tmp_path):
        """``repo_root``'s last resort is the filesystem root, and ``/`` contains everything.

        An installed wheel's ``SOURCE_ROOT`` can be ``parents[-1]``; a fence anchored there passes every write.
        """
        anchor = Path(tmp_path.anchor)
        target = tmp_path / "other_root" / ".trinity" / "local.json"

        refusal = write_fence.outside_root(target, anchor)

        assert refusal is not None and str(anchor) in refusal
        assert write_fence.outside_root(anchor, anchor) is not None

    def test_the_spawn_template_push_cannot_write_outside_the_root(self, tmp_path, monkeypatch):
        """The one .trinity writer that is not a branch: spawn's seed templates."""
        _home, foreign = self._fenced_world(tmp_path, monkeypatch)
        before = foreign.read_bytes()

        assert spawn_pusher._write_json(foreign, {"sessions": []}) is False
        assert foreign.read_bytes() == before

    def test_the_push_and_the_scope_module_resolve_the_same_fleet(self, live_fleet):
        """The two LANES answer the same fleet; the external tier is subtracted here, in the expectation."""
        in_repo = {
            item["name"]
            for item in registry_scope.fleet_branches(live_fleet)
            if item.get("residency") != registry_scope.RESIDENCY_EXTERNAL
        }
        assert in_repo, "an empty expectation would pass against an empty scope"
        assert {item["name"] for item in trinity_push.resolve_scope()["branches"]} == in_repo

    def test_a_missing_resident_registry_is_skipped_not_raised(self, tmp_path):
        """A checkout with no projects/ must not take out every fleet lane."""
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")

        assert registry_scope.resident_registry_paths(tmp_path) == []
        assert registry_scope.fleet_branches(tmp_path) == []

    def test_an_unreadable_registry_is_logged_not_fatal(self, tmp_path):
        broken = tmp_path / "AIPASS_REGISTRY.json"
        broken.write_text("{not json", encoding="utf-8")

        assert registry_scope.read_registry_branches(broken) == []

    def test_only_active_branches_are_in_scope(self, tmp_path):
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "branches": [
                        {"name": "live", "path": "src/live", "status": "active"},
                        {"name": "gone", "path": "src/gone", "status": "retired"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        names = [item["name"] for item in registry_scope.read_registry_branches(registry)]
        assert names == ["live"]

    def test_the_branch_name_is_its_directory_not_the_registrys_casing(self, tmp_path):
        """BACKUP vs backup: the checker compares managed_by to the DIRECTORY."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "BACKUP", "path": "src/backup", "status": "active"}]}),
            encoding="utf-8",
        )

        assert registry_scope.read_registry_branches(registry)[0]["name"] == "backup"
        assert registry_scope.read_registry_branches(registry, name_from="registry")[0]["name"] == "BACKUP"


# =============================================================================
# ITEM 2 — ROLLOVER NORMALIZES ON TOUCH, SCOPED
# =============================================================================


class TestRolloverHealsWhatItTouches:
    """A branch that rolls re-renders its OWN machine frame. Nobody else's."""

    @staticmethod
    def _drifted(tmp_path: Path, name: str) -> Path:
        root = tmp_path / name
        trinity = root / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text(
            json.dumps(
                {
                    "document_metadata": {"created": "2026-01-01", "status": {"health": "stale"}, "junk": 1},
                    "sessions": [{"number": 1, "date": "2026-08-27", "summary": "s", "status": "done"}],
                }
            ),
            encoding="utf-8",
        )
        (trinity / "observations.json").write_text(json.dumps({"observations": []}), encoding="utf-8")
        return root

    def test_normalizing_rebuilds_the_frame_as_the_closed_set(self, tmp_path):
        root = self._drifted(tmp_path, "guinea")

        result = normalizer.normalize_branch("guinea", root)

        assert result["success"] is True
        meta = json.loads((root / ".trinity" / "local.json").read_text(encoding="utf-8"))["document_metadata"]
        assert "status" not in meta
        assert "junk" not in meta
        assert meta["managed_by"] == "guinea"

    def test_normalizing_never_prunes_an_entry(self, tmp_path):
        """Rollover's frame heal is the FRAME. Archiving is the push's mandate.

        A normalize that pruned would be the push's dangerous half without any of its gates.
        """
        root = self._drifted(tmp_path, "guinea")
        local = root / ".trinity" / "local.json"
        data = json.loads(local.read_text(encoding="utf-8"))
        data["sessions"].append({"number": 2, "date": "2026-08-27", "summary": "s", "findings": ["drift"]})
        local.write_text(json.dumps(data), encoding="utf-8")

        normalizer.normalize_branch("guinea", root)

        sessions = json.loads(local.read_text(encoding="utf-8"))["sessions"]
        assert len(sessions) == 2
        assert any("findings" in entry for entry in sessions)

    def test_normalizing_is_scoped_to_the_named_branch(self, tmp_path):
        rolled = self._drifted(tmp_path, "rolled")
        bystander = self._drifted(tmp_path, "bystander")
        untouched = (bystander / ".trinity" / "local.json").read_bytes()

        normalizer.normalize_branch("rolled", rolled)

        assert (bystander / ".trinity" / "local.json").read_bytes() == untouched

    def test_a_branch_with_no_trinity_is_reported_not_crashed(self, tmp_path):
        result = normalizer.normalize_branch("ghost", tmp_path / "ghost")

        assert result["success"] is False
        assert "ghost" in result["error"]

    @staticmethod
    def _rolled(*branches: str) -> dict:
        """A handler result shaped as `run_rollover` renders it."""
        return {
            "success": True,
            "triggers_count": len(branches),
            "success_count": len(branches),
            "results": [
                {
                    "branch": name,
                    "success": True,
                    "local_stored": True,
                    "memories_count": 3,
                    "global_collection": "aipass_memory",
                    "old_lines": 700,
                    "new_lines": 400,
                    "global_total": 14061,
                }
                for name in branches
            ],
        }

    def test_the_rollover_actually_calls_the_normalizer(self):
        """The wiring, not just the handler: the other normalizer pins call the handler directly."""
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea")),
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs") as tabs,
            patch.object(rollover, "_normalize_rolled") as normalized,
        ):
            rollover.run_rollover()

        normalized.assert_called_once_with(["guinea"])
        tabs.assert_called_once_with(branches=["guinea"])

    def test_the_rollover_normalizes_only_the_branches_it_rolled(self):
        """A per-branch verb must not grow a fleet-wide tail."""
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea", "guinea")),
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs") as tabs,
            patch.object(rollover, "_normalize_rolled") as normalized,
        ):
            rollover.run_rollover()

        assert normalized.call_args.args[0] == ["guinea"]
        tabs.assert_called_once_with(branches=["guinea"])

    def test_nothing_rolled_means_nothing_normalized(self):
        """Idle costs nothing — the law of the marker, at the call site."""
        empty = self._rolled()
        empty["triggers_count"] = 1
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=empty),
            patch.object(rollover, "_normalize_rolled") as normalized,
        ):
            rollover.run_rollover()

        normalized.assert_not_called()

    def test_a_normalize_crash_never_retracts_a_finished_rollover(self):
        """The entries are already archived. A cosmetic re-render cannot undo that."""
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea")),
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs") as tabs,
            patch.object(normalizer, "normalize_branch", side_effect=RuntimeError("frame boom")),
            patch.object(
                registry_scope,
                "fleet_branches",
                return_value=[{"name": "guinea", "path": "/nowhere/guinea"}],
            ),
        ):
            assert rollover.run_rollover() is True

        tabs.assert_called_once_with(branches=["guinea"])

    def test_a_tab_refresh_crash_is_logged_as_an_error_and_keeps_the_rollover(self):
        """The rollover landed, so the run stands; the fault is an error, not a degradation."""
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea")),
            patch(
                "aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs",
                side_effect=RuntimeError("tab boom"),
            ),
            patch.object(rollover, "_normalize_rolled") as normalized,
            patch.object(rollover, "logger") as log,
        ):
            assert rollover.run_rollover() is True

        log.error.assert_any_call("[rollover] Tab refresh failed: tab boom")
        assert all("Tab refresh failed" not in str(call) for call in log.warning.call_args_list)
        normalized.assert_called_once_with(["guinea"])


# =============================================================================
# ITEM 5 — A VERB MAY NOT PROMISE A WRITE IT DOES NOT DO
# =============================================================================


class TestPushDefaultsWritesOnlyItsConfig:
    """push_defaults rewrites per_branch in the redirected config and touches nothing else."""

    @staticmethod
    def _tmp_fleet(tmp_path: Path, monkeypatch) -> tuple[list[Path], MagicMock]:
        """A one-citizen fleet under tmp_path, and the detector pointed at it.

        Both ``detector._REPO_ROOT`` and caller discovery are repointed, or the live fleet is in reach.
        """
        trinity = tmp_path / "guinea" / ".trinity"
        trinity.mkdir(parents=True)
        local = trinity / "local.json"
        local.write_text('{\n  "sessions": []\n}\n', encoding="utf-8")
        observations = trinity / "observations.json"
        observations.write_text('{\n  "observations": []\n}\n', encoding="utf-8")
        registry = {"branches": [{"name": "GUINEA", "path": "guinea", "status": "active"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        recorder = MagicMock()
        monkeypatch.setattr(rollover, "json_handler", recorder)
        return [local, observations], recorder

    def test_push_defaults_rewrites_per_branch_in_a_redirected_config(self, tmp_path, monkeypatch, capsys):
        """push_defaults, run for real — against a tmp_path config, never the operator's.

        It WRITES memory.config.json, so the redirect is proved before the call and the live file is hashed.
        """
        _files, recorder = self._tmp_fleet(tmp_path, monkeypatch)
        seeded = tmp_path / "memory.config.json"
        operator_file = _MEMORY_ROOT / "memory_json" / "custom_config" / "memory.config.json"
        seeded.write_text(
            json.dumps({"operator_key": "kept", "rollover": {"per_branch": {"stale": {"local": {}}}}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(config_loader, "_CONFIG_PATH", seeded)
        monkeypatch.setattr(config_loader, "_find_repo_root", lambda: tmp_path)
        assert sys.modules.get(config_loader.__name__) is config_loader, "the product would import an unpatched loader"
        live_before = hashlib.sha256(operator_file.read_bytes()).hexdigest() if operator_file.exists() else None

        rollover.push_defaults()

        live_after = hashlib.sha256(operator_file.read_bytes()).hexdigest() if operator_file.exists() else None
        assert live_after == live_before, "the operator's memory.config.json was written"
        written = json.loads(seeded.read_text(encoding="utf-8"))
        assert written["operator_key"] == "kept"
        assert set(written["rollover"]["per_branch"]) == {"guinea"}
        assert written["rollover"]["per_branch"]["guinea"]["local"]["todos"] == {"count": 10}
        assert "Pushed defaults to 1 branches" in capsys.readouterr().out
        recorder.log_operation.assert_called_once_with("push_defaults", {"branches": 1, "json": False})


# =============================================================================
# ITEM 6 — THE GRANDFATHER CLAUSE, NARROWED NOT REMOVED
# =============================================================================


class TestGrandfatherNarrowedToTodos:
    """A write is refused for what it AUTHORS: carried over-cap entries never brick a rollover.

    Identity is matched on text, not index: a prepend must not re-author the file.
    """

    @staticmethod
    def _limits(max_chars: int = 20) -> dict:
        """The shape load_entry_limits RETURNS — changed_entries takes that, not a branch."""
        return {
            "enabled": True,
            "enforce": True,
            "entry_types": {
                "sessions": {"container": "sessions", "field": "summary", "max_chars": max_chars, "kind": "list"},
                "todos": {"container": "todos", "field": "task", "max_chars": max_chars, "kind": "list"},
            },
        }

    def test_an_unchanged_over_cap_session_is_carried_not_a_violation(self):
        fat = {"number": 1, "date": "2026-08-27", "summary": "x" * 99, "status": "done"}
        before = {"sessions": [fat]}
        after = {"sessions": [dict(fat)]}

        assert entry_limits.changed_entries(before, after, self._limits()) == []

        carried = entry_limits.classify_entries(before, after, self._limits())["carried"]
        assert [hit["entry_type"] for hit in carried] == ["sessions"]

    def test_an_unchanged_over_cap_todo_is_still_exempt(self):
        """The one container the push may not cure keeps its exemption."""
        fat = {"number": 1, "date": "2026-08-27", "task": "x" * 99, "priority": "high", "status": "open"}
        before = {"todos": [fat]}
        after = {"todos": [dict(fat)]}

        hits = entry_limits.changed_entries(before, after, self._limits())

        assert hits == []

    def test_a_maintenance_write_to_a_drifted_todo_branch_is_not_bricked(self):
        """Rollover must still be able to write a file carrying a debt it cannot prune."""
        fat_todo = {"number": 1, "date": "2026-08-27", "task": "x" * 99, "priority": "high", "status": "open"}
        before = {"todos": [fat_todo], "sessions": [{"number": 1, "date": "d", "summary": "ok", "status": "s"}]}
        after = {"todos": [dict(fat_todo)], "sessions": []}

        hits = entry_limits.changed_entries(before, after, self._limits())

        assert hits == []

    def test_a_new_over_cap_todo_is_still_refused(self):
        """The exemption covers what is already on disk, never a fresh violation."""
        before = {"todos": []}
        after = {"todos": [{"number": 1, "date": "d", "task": "y" * 99, "priority": "p", "status": "s"}]}

        hits = entry_limits.changed_entries(before, after, self._limits())

        assert [hit["entry_type"] for hit in hits] == ["todos"]

    def test_the_reshape_only_constant_is_retired_from_both_modules(self):
        """Zero consumers, so retired: a copy in either module is the old never-move exemption back."""
        assert not hasattr(entry_limits, "RESHAPE_ONLY_SECTIONS")
        assert not hasattr(trinity_push, "RESHAPE_ONLY_SECTIONS")


# =============================================================================
# ITEM 1 — A TEMPLATE BUMP HEALS THROUGH THE PUSH'S GATES
# =============================================================================


class TestTemplateBumpFiresThePush:
    """The bump is the trigger. The push is the lane. The gates stay on."""

    def test_a_matching_ledger_reports_no_bump(self, tmp_path, monkeypatch):
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: tmp_path / "ledger.json")
        gold = template_bump.gold_versions()
        (tmp_path / "ledger.json").write_text(json.dumps({"template_versions": gold}), encoding="utf-8")

        assert template_bump.bump_pending()["pending"] is False

    def test_a_stale_ledger_reports_the_bump_with_both_versions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: tmp_path / "ledger.json")
        (tmp_path / "ledger.json").write_text(
            json.dumps({"template_versions": {"local": "0.0.1", "observations": "0.0.1"}}), encoding="utf-8"
        )

        pending = template_bump.bump_pending()

        assert pending["pending"] is True
        assert pending["was"] == {"local": "0.0.1", "observations": "0.0.1"}
        assert pending["now"] == template_bump.gold_versions()

    def test_no_ledger_at_all_reports_a_bump_never_a_silent_pass(self, tmp_path, monkeypatch):
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: tmp_path / "absent.json")

        assert template_bump.bump_pending()["pending"] is True

    def test_the_retired_lanes_own_ledger_shape_reads_as_pending_not_as_current(self, tmp_path, monkeypatch):
        """The retired lane's `{last_push, ...}` ledger is no answer: only `template_versions` is."""
        ledger = tmp_path / "ledger.json"
        ledger.write_text(
            json.dumps({"last_push": "2026-06-25 01:55:01", "last_push_branches": ["COMMONS", "HOOKS"]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: ledger)

        pending = template_bump.bump_pending()

        assert pending["pending"] is True
        assert pending["was"] is None

    def test_an_unreadable_ledger_is_pending_not_a_crash(self, tmp_path, monkeypatch):
        ledger = tmp_path / "ledger.json"
        ledger.write_text("{not json at all", encoding="utf-8")
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: ledger)

        assert template_bump.bump_pending()["pending"] is True

    def test_a_bump_runs_the_push_as_a_dry_run_by_default(self, tmp_path, monkeypatch):
        """Self-healing 22 branches' memory files unprompted is not healing."""
        calls = []
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: tmp_path / "absent.json")
        monkeypatch.setattr(
            template_bump, "_run_push", lambda dry_run: calls.append(dry_run) or {"success": True, "branches": []}
        )

        template_bump.on_bump()

        assert calls == [True]

    def test_the_ledger_is_only_stamped_by_a_real_push(self, tmp_path, monkeypatch):
        """A dry-run that recorded the version would tell the next bump it already ran."""
        ledger = tmp_path / "ledger.json"
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: ledger)
        monkeypatch.setattr(template_bump, "_run_push", lambda dry_run: {"success": True, "branches": []})

        template_bump.on_bump(confirm=False)
        assert not ledger.exists()

        template_bump.on_bump(confirm=True)
        assert json.loads(ledger.read_text(encoding="utf-8"))["template_versions"] == template_bump.gold_versions()

    def test_a_failed_push_never_stamps_the_ledger(self, tmp_path, monkeypatch):
        ledger = tmp_path / "ledger.json"
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: ledger)
        monkeypatch.setattr(template_bump, "_run_push", lambda dry_run: {"success": False, "errors": ["boom"]})

        template_bump.on_bump(confirm=True)

        assert not ledger.exists()

    def test_the_handler_owns_the_events_name_and_not_its_sending(self):
        """The name lives with the fact; reaching @trigger's bus lives with the caller.

        A handler must not import another branch's module layer; asserted at source.
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "template_bump.py").read_text(encoding="utf-8")

        assert template_bump.BUMP_EVENT == "trinity_template_bumped"
        assert "aipass.trigger" not in source

    def test_the_bump_announces_itself_on_the_bus(self, monkeypatch):
        """Trigger-driven, never a poller: the bump ANNOUNCES what it did.

        The real call path: the payload is built inside a best-effort try, so a broken one is swallowed.
        Real packages with `__path__`, not MagicMocks: on 3.10 the lazy import traverses the parent.
        The reachability check runs first, so "never reached" and "chose not to fire" stay apart.
        """
        fired = []

        class _Bus:
            @staticmethod
            def fire(event, **data):
                fired.append((event, data))

        for name in ("aipass.trigger", "aipass.trigger.apps", "aipass.trigger.apps.modules"):
            package = types.ModuleType(name)
            package.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, name, package)
        bus_module = types.ModuleType("aipass.trigger.apps.modules.core")
        bus_module.trigger = _Bus  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", bus_module)

        # Exactly what `from X import trigger` compiles to: no route the code under test does not take.
        reached = __import__("aipass.trigger.apps.modules.core", fromlist=["trigger"])
        assert reached.trigger is _Bus, "the bus stand-in is not reachable by the import _announce_bump uses"

        templates._announce_bump({"pending": True, "dry_run": True, "stamped": False, "now": {"local": "3.0.0"}})

        assert [event for event, _ in fired] == [template_bump.BUMP_EVENT]
        payload = fired[0][1]
        assert payload["pending"] is True and payload["dry_run"] is True and payload["stamped"] is False
        assert json.loads(payload["versions"]) == {"local": "3.0.0"}

    def test_a_dead_bus_never_blocks_the_heal(self, monkeypatch):
        """Best effort means best effort — a listener's absence cannot gate a push."""
        monkeypatch.setattr(template_bump, "_run_push", lambda dry_run: {"success": True, "branches": []})
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: _MEMORY_ROOT / "no-such-ledger.json")

        with patch("aipass.memory.apps.modules.templates._announce_bump", side_effect=RuntimeError("bus on fire")):
            outcome = template_bump.on_bump()

        assert outcome["pending"] is True and outcome["push"] == {"success": True, "branches": []}

    def test_the_bump_verb_announces_after_the_outcome_is_known(self, monkeypatch, capsys):
        """A listener must never be told a heal ran when the push refused."""
        seen = []
        monkeypatch.setattr(template_bump, "_ledger_path", lambda: _MEMORY_ROOT / "no-such-ledger.json")
        monkeypatch.setattr(
            template_bump,
            "_run_push",
            lambda dry_run: {"success": False, "dry_run": dry_run, "scope": 0, "branches": [], "errors": ["refused"]},
        )
        monkeypatch.setattr(templates, "_announce_bump", lambda outcome: seen.append(outcome))

        templates.handle_command("templates", ["bump", "--confirm"])
        capsys.readouterr()

        assert len(seen) == 1
        assert seen[0]["stamped"] is False, "announced a stamp the push never earned"


# =============================================================================
# ITEM 3 — A LANE AIMED AT A DEAD LAYOUT IS RETIRED, NOT LEFT LOADED
# =============================================================================


class TestTheDeadTemplateLaneIsRetired:
    """`push-templates` and `diff-templates` scanned a pre-.trinity layout; the spawn half is kept."""

    def test_the_dead_handlers_are_out_of_the_live_tree(self):
        """Not importable is the point: a no-op nobody can call cannot be trusted."""
        handlers = _MEMORY_ROOT / "apps" / "handlers" / "templates"

        assert not (handlers / "pusher.py").exists()
        assert not (handlers / "differ.py").exists()

    def test_no_live_handler_still_scans_the_pre_trinity_layout(self):
        """The suffix scan is what made zero matches possible. It is gone everywhere."""
        live = _walk(_MEMORY_ROOT / "apps")
        offenders = [
            path.name
            for path in live
            if '.endswith(".local.json")' in path.read_text(encoding="utf-8")
            or '.endswith(".observations.json")' in path.read_text(encoding="utf-8")
        ]

        assert offenders == []

    def test_the_park_keeps_them_with_the_measurement(self):
        """Never a casual delete — the record of WHY outlives the code.

        A TRACKED park, not `.archive/`: `.archive/` is gitignored and present in no clone.
        """
        parked = _MEMORY_ROOT / "tests" / "parked" / "dead_template_lane_20260827"

        assert (parked / "pusher(disabled).py").is_file()
        assert (parked / "differ(disabled).py").is_file()
        assert not (_MEMORY_ROOT / ".archive" / "dead_template_lane_20260827").exists()
        assert "zero real matches" in (parked / "README.md").read_text(encoding="utf-8").lower()

    def test_the_parked_lane_is_never_collected_as_tests(self):
        """Two of the parked files are named `test_*` — the barrier must hold."""
        parked = _MEMORY_ROOT / "tests" / "parked" / "dead_template_lane_20260827"

        assert (parked / "test_templates(disabled).py").is_file()
        assert (parked / "test_templates_display(disabled).py").is_file()
        assert (_MEMORY_ROOT / "tests" / "parked" / "conftest.py").is_file()

    def test_the_retired_verbs_refuse_and_name_the_live_lane(self, capsys):
        """A refusal that exits 0 is half a refusal: claimed, exit 2, and the live lane named."""
        for verb in ("push-templates", "diff-templates"):
            reset_command_state()
            assert templates.handle_command(verb, ["--dry-run"]) is True
            assert resolve_exit(True) == 2, f"{verb} refused but would exit 0"
            printed = capsys.readouterr().out
            assert "push" in printed.lower()

    def test_the_spawn_scaffold_lane_survives(self):
        assert hasattr(spawn_pusher, "push_to_spawn_templates")

    def test_template_status_reports_the_live_receipts(self, live_fleet):
        """Status reads every citizen's live receipt off disk, so it needs a real fleet."""
        status = template_bump.receipt_status()

        assert status["gold"] == template_bump.gold_versions()
        assert status["branches"], "no branch receipts read"
        assert all("branch" in row and "carries" in row for row in status["branches"])


# Existence is not sufficiency: a live guard reads the rows, not the filename, one question per fixture.
# Ground truth is read with pathlib and json, NEVER through registry_scope, or a resolver regression is a SKIP.


class TestTheLiveGuardRefusesAHalfPresentWorld:
    """The fixtures themselves, against stand-in worlds built on disk."""

    @staticmethod
    def _world(
        tmp_path,
        *,
        rows,
        residents=False,
        roots=False,
        external_citizen=False,
        registered_but_absent=False,
        dict_shaped=False,
    ):
        """Build a stand-in repo root with a chosen subset of the three tiers."""
        root = tmp_path / "standin_repo"
        (root / "src" / "aipass").mkdir(parents=True)

        if rows is not None:
            (root / "AIPASS_REGISTRY.json").write_text(
                json.dumps({"metadata": {"version": "1.0.0"}, "branches": rows}, indent=2),
                encoding="utf-8",
            )
        if residents:
            for project, stem in (
                ("baud", "BAUD"),
                ("earmark", "EARMARK"),
                ("finch", "FINCH"),
                ("aipass-site", "AIPASS-SITE"),
            ):
                directory = root / "projects" / project
                directory.mkdir(parents=True)
                (directory / f"{stem}_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        if roots:
            sibling = tmp_path / "Sibling-Repo"
            sibling.mkdir()
            if external_citizen or registered_but_absent:
                rows_json = (
                    {"wren": {"name": "wren", "path": "wren"}} if dict_shaped else [{"name": "wren", "path": "wren"}]
                )
                (sibling / "SIBLING_REGISTRY.json").write_text(json.dumps({"branches": rows_json}), encoding="utf-8")
            if external_citizen:
                trinity = sibling / "wren" / ".trinity"
                trinity.mkdir(parents=True)
                (trinity / "passport.json").write_text(json.dumps({"branch_info": {}}), encoding="utf-8")
            (root / "AIPASS_ROOTS.json").write_text(
                json.dumps({"roots": [{"path": "../Sibling-Repo"}]}, indent=2), encoding="utf-8"
            )
        return root

    @staticmethod
    def _resolved(request, name):
        """Resolve a guard fixture, turning an over-skip into a RED.

        A skip inside a fixture reads as green, so an unconditional-skip mutant would silence the positive pins.
        """
        try:
            return request.getfixturevalue(name)
        except Skipped as skipped:  # re-raised as a failure, deliberately
            pytest.fail(f"{name} skipped a world it should have accepted: {skipped}")

    @staticmethod
    def _point_both_lanes_at(monkeypatch, root):
        """Both roots move together — a guard reading one lane is half a guard."""
        monkeypatch.setattr(registry_scope, "REPO_ROOT", root)
        monkeypatch.setattr(trinity_push, "_REPO_ROOT", root)

    _CORE_ROWS = [{"name": "memory", "path": "src/aipass/memory"}]

    def test_a_registry_that_exists_but_holds_no_rows_is_not_a_fleet(self, request, monkeypatch, tmp_path):
        """The minted-empty case. `push_names <= registry_names` is true of nothing."""
        self._point_both_lanes_at(monkeypatch, self._world(tmp_path, rows=[]))

        with pytest.raises(Skipped) as skipped:
            request.getfixturevalue("live_fleet")
        assert "no branch rows" in str(skipped.value)

    def test_an_unreadable_registry_is_absence_not_presence(self, request, monkeypatch, tmp_path):
        """Corrupt is not a fleet either — and it must not raise out of a guard."""
        root = self._world(tmp_path, rows=self._CORE_ROWS)
        (root / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
        self._point_both_lanes_at(monkeypatch, root)

        with pytest.raises(Skipped):
            request.getfixturevalue("live_fleet")

    def test_a_real_core_registry_still_passes_the_guard(self, request, monkeypatch, tmp_path):
        """The hardening must not convert honest core coverage into skips."""
        root = self._world(tmp_path, rows=self._CORE_ROWS)
        self._point_both_lanes_at(monkeypatch, root)

        assert self._resolved(request, "live_fleet") == root

    def test_the_ci_shape_is_refused_by_the_three_tier_guard(self, request, monkeypatch, tmp_path):
        """THE CI FAILURE, as a test: core rows present, residents and externals absent."""
        self._point_both_lanes_at(monkeypatch, self._world(tmp_path, rows=self._CORE_ROWS))

        with pytest.raises(Skipped) as skipped:
            request.getfixturevalue("live_all_tiers")
        assert "resident" in str(skipped.value).lower()

    def test_residents_without_a_roots_file_is_still_half_present(self, request, monkeypatch, tmp_path):
        """Two tiers is not three. The roots anchor is machine-local and gitignored."""
        root = self._world(tmp_path, rows=self._CORE_ROWS, residents=True)
        self._point_both_lanes_at(monkeypatch, root)

        with pytest.raises(Skipped) as skipped:
            request.getfixturevalue("live_all_tiers")
        assert registry_scope.DECLARED_ROOTS in str(skipped.value)

    def test_a_roots_file_declaring_nothing_reachable_is_not_a_third_tier(self, request, monkeypatch, tmp_path):
        """A declaration is not a citizen. The anchor can be present and empty."""
        root = self._world(tmp_path, rows=self._CORE_ROWS, residents=True, roots=True)
        self._point_both_lanes_at(monkeypatch, root)

        with pytest.raises(Skipped) as skipped:
            request.getfixturevalue("live_all_tiers")
        assert "external" in str(skipped.value).lower()

    def test_a_genuine_three_tier_world_passes(self, request, monkeypatch, tmp_path):
        """All three tiers really on disk — the guard must let the assertion run.

        Without this the class is satisfied by a fixture that skips unconditionally.
        """
        root = self._world(tmp_path, rows=self._CORE_ROWS, residents=True, roots=True, external_citizen=True)
        self._point_both_lanes_at(monkeypatch, root)

        assert self._resolved(request, "live_all_tiers") == root

    def test_a_registered_external_branch_with_no_passport_is_not_a_citizen(self, request, monkeypatch, tmp_path):
        """A ROW is not a citizen either: membership is PRESENCE, so a registered but absent `wren` is not one."""
        root = self._world(tmp_path, rows=self._CORE_ROWS, residents=True, roots=True, registered_but_absent=True)
        self._point_both_lanes_at(monkeypatch, root)

        with pytest.raises(Skipped) as skipped:
            request.getfixturevalue("live_all_tiers")
        assert "external" in str(skipped.value).lower()

    def test_a_dict_shaped_registry_is_read_not_called_empty(self, request, monkeypatch, tmp_path):
        """Both registry shapes ship. A reader that knows one calls half the fleet empty."""
        root = self._world(
            tmp_path,
            rows={"memory": {"name": "memory", "path": "src/aipass/memory"}},
            residents=True,
            roots=True,
            external_citizen=True,
            dict_shaped=True,
        )
        self._point_both_lanes_at(monkeypatch, root)

        assert self._resolved(request, "live_all_tiers") == root

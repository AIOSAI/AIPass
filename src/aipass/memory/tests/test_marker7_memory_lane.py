# =================== AIPass ====================
# Name: test_marker7_memory_lane.py
# Description: Red-first pins for marker 7 — self-healing triggers and the aftercare rulings
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Marker 7 — the memory lane, and the rulings that came with it.

THE LAW OF THE MARKER: self-healing is TRIGGER-DRIVEN, never a daemon. Idle
means zero processes.  Every pin here is written against that shape — a lane
that heals because something HAPPENED, not because something is watching.

The five behaviours under test, and the wrong implementation each pin kills:

- **One fleet, one definition** — rollover/lint/health reaching 19 branches
  while the push reaches 22, so three citizens' memories could overflow with
  no rollover ever running on them.
- **Rollover normalizes on touch, SCOPED** — a branch that rolls heals its own
  machine frame; healing the fleet from one branch's rollover is the 23:37
  write that opened this whole arc.
- **A verb whose name promises a write it no longer does** — `sync-lines`
  stopped writing when the health stamp was deleted, and kept the name.
- **The grandfather clause, narrowed not removed** — post-push the fleet is
  green, so "unchanged and over cap" hides new drift for the three archivable
  containers; for `todos` it is the only thing standing between a branch the
  push may not prune and a rollover lane that refuses to write to it.
- **A template bump heals through the push's gates** — never around them.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

# Imported at MODULE level on purpose. conftest's autouse fixture replaces
# `aipass.memory.apps.handlers.json` with a MagicMock package for the duration
# of each test, so any handler importing `...handlers.json.memory_files` from
# inside a test body raises "not a package". Collection-time imports resolve
# against the real modules and are cached — the pattern the rest of the suite
# already follows.
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.templates import trinity_push
from aipass.memory.apps.handlers.templates import template_bump
from aipass.memory.apps.handlers.rollover import normalizer
from aipass.memory.apps.handlers.json import entry_limits
from aipass.memory.apps.handlers.tracking import line_counter
from aipass.memory.apps.handlers.templates import spawn_pusher
from aipass.memory.apps.modules import rollover
from aipass.memory.apps.modules import templates


_MEMORY_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _MEMORY_ROOT.parents[2]


# =============================================================================
# ITEM 7 — ONE FLEET, ONE DEFINITION
# =============================================================================


class TestOneFleetOneDefinition:
    """Every @memory lane answers "which branches?" from the same source.

    Mutation notes: dropping a resident from the constant, letting the scope
    fall back to a glob over projects/ (which would sweep the held
    marketstand), or leaving detector reading only the core registry.
    """

    def test_the_fleet_reaches_all_four_resident_projects(self, live_residents):
        """Repointed 2026-08-28: there is no constant to read any more.

        This used to join the named tuple into a string and look for four
        substrings — a test that two literals agreed, which would have passed
        just as happily if the resolver had stopped working entirely. It now
        asks the resolver, which is the thing that has to be right.
        """
        names = {item["name"] for item in registry_scope.fleet_branches(live_residents)}
        assert {"baud", "earmark", "finch", "aipass_site"} <= names

    def test_a_held_project_is_never_swept_in(self, live_fleet):
        """marketstand marks its branch active INSIDE a directory named (on _hold).

        Guarded even though it passes on a clean checkout: with no registry the
        scope is EMPTY, and `"marketstand" not in set()` is true for the one
        reason that makes the assertion worthless. A green that measures
        nothing is the failure mode this branch keeps finding in other lanes.
        """
        names = [item["name"] for item in registry_scope.fleet_branches()]
        assert "marketstand" not in names
        assert not any("hold" in name for name in names)

    def test_the_shared_scope_reaches_every_resident(self, live_residents):
        """Guarded on the RESIDENT FILES, not just on "aipass is installed".

        The Windows e2e lane installs aipass from the wheel: a real registry,
        the core citizens, and none of the four residents — which live in
        `projects/` on one machine. `live_fleet` correctly called that a live
        installation and let this run, and it failed on a claim that was never
        about the software. `live_residents` reads the four registry files off
        disk with pathlib; present-but-unreachable is still a failure.
        """
        names = {item["name"] for item in registry_scope.fleet_branches()}
        assert {"earmark", "finch", "aipass_site", "baud"} <= names

    def test_the_push_and_the_registry_lane_agree_on_the_fleet(self, live_fleet):
        """The two lanes disagreeing by three citizens is the defect being closed.

        Guarded for the same reason as the held-project pin: two empty sets
        satisfy `<=` and agree about nothing.
        """
        push_names = {item["name"].lower() for item in trinity_push.resolve_scope()["branches"]}
        registry_names = {Path(item["path"]).name.lower() for item in detector._read_registry()}
        assert push_names <= registry_names, f"invisible to rollover/lint/health: {push_names - registry_names}"

    def test_the_push_never_reaches_into_another_repository(self, live_fleet):
        """The template push WRITES. So its scope stops at this repo's edge.

        `fleet_branches` grew an external tier in 3.0.0 and this lane consumes
        it, which briefly put six citizens in four sibling repositories into the
        scope of a lane whose whole job is writing files into branches. Nothing
        in the external tier build writes to another repo, and the push must not
        become the exception.

        The reader is not wrong and the consumer is not wrong about which
        function to call — the scope is the thing that needed narrowing, at the
        one lane that acts on it rather than reads it.
        """
        scoped = trinity_push.resolve_scope()["branches"]
        assert scoped, "empty scope proves nothing about what it excludes"
        outsiders = [item for item in scoped if item.get("residency") == registry_scope.RESIDENCY_EXTERNAL]
        assert not outsiders, f"the push would write into another repository: {[i['name'] for i in outsiders]}"
        assert all(str(item["path"]).startswith(str(registry_scope.REPO_ROOT)) for item in scoped)

    def test_every_fleet_record_carries_exactly_the_five_agreed_keys(self, live_fleet):
        """The whole record shape, across ALL THREE TIERS, not just externals.

        The `scheduler` field was withdrawn from the record on 2026-08-30 at the
        request of the only branch that ever wanted it, and the replacement pin
        was written against `external_branches` alone. So core and resident rows
        were unpinned: a mutant re-adding `item["scheduler"]` to the core loop
        passed the entire suite. A record nobody consumes should have to come
        past a test on the way in — which only works if the test covers the
        tiers a new field would actually be added to.
        """
        rows = registry_scope.fleet_branches(live_fleet)
        assert rows, "an empty fleet proves nothing about record shape"
        tiers = {row["residency"] for row in rows}
        assert tiers == {
            registry_scope.RESIDENCY_CORE,
            registry_scope.RESIDENCY_RESIDENT,
            registry_scope.RESIDENCY_EXTERNAL,
        }, f"all three tiers must be exercised, got {tiers}"
        for row in rows:
            assert set(row) == {"name", "path", "registry", "email", "residency"}, row

    def test_the_normalize_lane_never_reaches_into_another_repository(self, monkeypatch):
        """The third writing lane, found by @trigger's escalation not by design.

        `_normalize_rolled` resolved `fleet_branches()` — the whole fleet,
        externals included — and then matched rolled branches BY NAME. It
        writes: `normalize_branch` re-renders the machine frame in place. So the
        day any external project names a branch `api` or `flow`, rolling our own
        @api would silently rewrite a file in a sibling repository.

        There is no collision today; that is luck, not a guard. Six external
        names against twenty-two of ours, and nothing stops the twenty-third.
        """
        from aipass.memory.apps.handlers.rollover import normalizer
        from aipass.memory.apps.modules import rollover as rollover_module

        seen = []
        monkeypatch.setattr(
            normalizer,
            "normalize_branch",
            lambda name, path, config: seen.append((name, Path(path))) or {"success": True},
        )
        # Every citizen in the fleet claims to have rolled, external ones included.
        every_name = [item["name"] for item in registry_scope.fleet_branches()]
        rollover_module._normalize_rolled(every_name)

        assert seen, "nothing was normalized, so the scope was never exercised"
        home = registry_scope.REPO_ROOT.resolve()
        outside = [p for _, p in seen if home not in p.resolve().parents and p.resolve() != home]
        assert not outside, f"normalize would write outside this repo: {outside}"

    def test_a_branch_whose_frame_could_not_be_written_is_named(self, monkeypatch, caplog):
        """The normalizer reports failure by return value; the caller dropped it.

        `if normalize_branch(...)["success"]:` — a False just failed to
        increment a counter. The `except` below it catches exceptions the
        normalizer explicitly promises never to raise, so it was decorative.
        Meanwhile the out-of-scope case IS named. One failure mode announced,
        the other invisible, in the same function.
        """
        from aipass.memory.apps.handlers.rollover import normalizer
        from aipass.memory.apps.modules import rollover as rollover_module

        monkeypatch.setattr(
            normalizer,
            "normalize_branch",
            lambda name, path, config: {"success": False, "error": f"{name}: local.json write failed"},
        )
        # Captured at the logger, not via caplog: prax's logger does not
        # necessarily propagate to the root under every suite ordering, and a
        # pin that only holds when it runs first is not a pin.
        said = []
        monkeypatch.setattr(rollover_module.logger, "warning", lambda msg, *a, **k: said.append(str(msg)))

        rollover_module._normalize_rolled(["memory"])

        joined = " ".join(said)
        assert "memory" in joined, joined
        assert "write failed" in joined, joined

    def test_the_rollover_lane_never_reaches_into_another_repository(self, live_fleet):
        """Rollover WRITES too — it trims memory files. Same edge as the push.

        The detector resolves through `accepted_resident_paths`, not
        `fleet_branches`, so it never inherited the external tier. That is the
        correct scope and this pins it, because repointing the detector at the
        richer function is an obvious-looking one-line "simplification" and it
        would put four sibling repositories inside the write scope of a lane
        that edits other citizens' memories.

        Measured while writing it: three external citizens (@verify, @vera,
        @research) carry 49 over-cap entries between them. Rollover reaching
        them would be a lane writing into repos nobody declared it for.
        """
        from aipass.memory.apps.handlers.monitor import detector

        rolled = {Path(item["path"]).resolve() for item in detector._read_registry()}
        assert rolled, "an empty scope proves nothing about what it excludes"
        home = registry_scope.REPO_ROOT.resolve()
        outside = [p for p in rolled if home not in p.parents and p != home]
        assert not outside, f"rollover would write outside this repo: {outside}"

    def test_the_push_and_the_scope_module_resolve_the_same_fleet(self, live_fleet):
        """Repointed 2026-08-28: the shared constant is gone, the agreement is not.

        Comparing two re-exported tuples proved they were the same object. The
        claim worth holding is that the two LANES answer the same question the
        same way, which survives the constant and would have caught the split
        this module was built to end.

        Narrowed 2026-08-30: the push answers the same question, over the tiers
        that live in this repository. The external tier is subtracted HERE, in
        the expectation, so the difference between the two lanes stays one named
        line of test rather than a drift nobody wrote down.
        """
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
    """A branch that rolls re-renders its OWN machine frame. Nobody else's.

    Mutation notes: normalizing every branch instead of the rolled one (the
    23:37 fleet write, wearing a new hat), normalizing nothing, or letting a
    normalize failure take down the rollover that already succeeded.
    """

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

        A normalize that quietly pruned would be a vectorize-verify-prune lane
        running with no report, no receipt and no note — the push's dangerous
        half without any of its gates.
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
        """The wiring, not just the handler.

        Found by mutation: deleting the `_normalize_rolled(rolled)` call from
        `run_rollover` left all four normalizer pins green, because every one
        of them calls the handler directly. A self-healing lane nothing invokes
        is a lane that does not exist.
        """
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea")),
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs"),
            patch.object(rollover, "_normalize_rolled") as normalized,
        ):
            rollover.run_rollover()

        normalized.assert_called_once_with(["guinea"])

    def test_the_rollover_normalizes_only_the_branches_it_rolled(self):
        """The 2026-08-25 shape: a per-branch verb with a fleet-wide tail."""
        with (
            patch.object(rollover, "_handler_execute_rollover", return_value=self._rolled("guinea", "guinea")),
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs"),
            patch.object(rollover, "_normalize_rolled") as normalized,
        ):
            rollover.run_rollover()

        assert normalized.call_args.args[0] == ["guinea"]

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
            patch("aipass.memory.apps.handlers.tracking.tab_renderer.refresh_all_tabs"),
            patch.object(normalizer, "normalize_branch", side_effect=RuntimeError("frame boom")),
            patch.object(
                registry_scope,
                "fleet_branches",
                return_value=[{"name": "guinea", "path": "/nowhere/guinea"}],
            ),
        ):
            assert rollover.run_rollover() is True


# =============================================================================
# ITEM 5 — A VERB MAY NOT PROMISE A WRITE IT DOES NOT DO
# =============================================================================


class TestSyncLinesTellsTheTruth:
    """`sync-lines` wrote nothing after the health stamp was deleted.

    Mutation notes: keeping the old name silently, or keeping the unscoped
    fleet-wide `refresh_all_tabs()` inside what is now a read-only reporter.
    """

    def test_the_reporter_verb_exists_under_a_true_name(self):
        assert "report-lines" in rollover.SUBCOMMANDS

    def test_the_old_name_still_routes_and_says_what_changed(self):
        """Never a silent removal: the old verb answers, and names its successor."""
        assert rollover.handle_command("rollover", ["sync-lines"]) is True

    def test_the_reporter_does_not_re_render_the_fleets_tabs(self):
        """A read-only reporter that rewrites 22 branches' files is the old lie again."""
        source = (_MEMORY_ROOT / "apps" / "modules" / "rollover.py").read_text(encoding="utf-8")
        body = source.split("def report_line_counts")[1].split("\ndef ")[0]

        assert "refresh_all_tabs" not in body

    def test_the_line_counter_still_writes_nothing(self, tmp_path):
        target = tmp_path / "local.json"
        target.write_text(json.dumps({"sessions": []}), encoding="utf-8")
        before = target.read_bytes()

        result = line_counter.update_line_count(target)

        assert result["success"] is True
        assert target.read_bytes() == before


# =============================================================================
# ITEM 6 — THE GRANDFATHER CLAUSE, NARROWED NOT REMOVED
# =============================================================================


class TestGrandfatherNarrowedToTodos:
    """The clause was narrowed to todos on 2026-08-27 and widened back on 08-30.

    The narrowing's own argument for the todos exemption — refusing every
    write to a file carrying a debt no machine may prune BRICKS that branch's
    rollover, the slow-motion data loss item 7 exists to prevent — turned out
    to hold for every container, because rollover's write is always a shrink
    and it may not touch the entry it is refused for. Three hours of identical
    errors were the receipt.

    So the rule is one rule now: a write is refused for what it AUTHORS.
    todos are no longer a special case at the cap gate; they remain the one
    container the PUSH may not prune, which is a different question and keeps
    its own constant.

    Mutation notes: refusing carried entries (deadlocks rollover), skipping
    carried entries silently (the 08-27 objection, still valid), or matching
    list identity on index instead of text (a prepend re-authors the file).
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

    def test_a_NEW_over_cap_todo_is_still_refused(self):
        """The exemption covers what is already on disk, never a fresh violation."""
        before = {"todos": []}
        after = {"todos": [{"number": 1, "date": "d", "task": "y" * 99, "priority": "p", "status": "s"}]}

        hits = entry_limits.changed_entries(before, after, self._limits())

        assert [hit["entry_type"] for hit in hits] == ["todos"]

    def test_the_exemption_is_keyed_on_the_pushs_own_constant(self):
        """Two lists of exempt containers would drift apart in a week."""
        assert entry_limits.RESHAPE_ONLY_SECTIONS == trinity_push.RESHAPE_ONLY_SECTIONS


# =============================================================================
# ITEM 1 — A TEMPLATE BUMP HEALS THROUGH THE PUSH'S GATES
# =============================================================================


class TestTemplateBumpFiresThePush:
    """The bump is the trigger. The push is the lane. The gates stay on.

    Mutation notes: firing a WRITING push from a bump (a fleet-wide unprompted
    rewrite, the exact thing --confirm exists to stop), reporting no drift when
    the ledger is stale, or recording the new version when the push refused.
    """

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
        """A real fossil, found on disk 2026-08-27 in `memory/templates/`.

        The dead pre-`.trinity` pusher wrote `{last_push, last_push_branches}`
        — a date and sixteen uppercase branch names, no version anywhere. A
        reader that treated "a ledger exists" as "the fleet is current" would
        take that file's word for a push that happened in June, through a lane
        that could never match a memory file. Only `template_versions` is an
        answer; every other shape is an absence wearing a record's clothes.
        """
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

    def test_a_bump_runs_the_push_as_a_DRY_RUN_by_default(self, tmp_path, monkeypatch):
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

        A handler that imports another branch's module layer is orchestration
        in domain-logic clothes. So `template_bump` names the event and never
        sends it — asserted at source, because "it happens not to import it
        today" is not the same promise as "it must not".
        """
        source = (_MEMORY_ROOT / "apps" / "handlers" / "templates" / "template_bump.py").read_text(encoding="utf-8")

        assert template_bump.BUMP_EVENT == "trinity_template_bumped"
        assert "aipass.trigger" not in source

    def test_the_bump_announces_itself_on_the_bus(self, monkeypatch):
        """Trigger-driven, never a poller: the bump ANNOUNCES what it did.

        Fires through the REAL call path with a real outcome dict — the payload
        is built inside the try, so a broken payload expression is swallowed by
        the best-effort catch and the announcement silently never happens. That
        shipped once (`json` unimported); only an end-to-end pin bites it.

        REAL MODULE OBJECTS, NOT MagicMocks, and not a string-target `patch`.
        `_announce_bump` imports the bus INSIDE the function, so what it gets
        depends on import machinery. conftest's autouse fixture puts MagicMocks
        in `sys.modules` for the `aipass.trigger` chain, and a MagicMock has no
        `__path__` — so `from aipass.trigger.apps.modules.core import trigger`
        resolves only while the interpreter serves the leaf straight out of
        `sys.modules`. 3.12 does; 3.10 entered the parent traversal, raised
        ModuleNotFoundError, and `_announce_bump` swallowed it by design —
        green on three interpreters and red on the fourth, for a reason that
        had nothing to do with the behaviour under test.

        Packages carry `__path__` here, so the import resolves the same way on
        every version. And the reachability check below runs FIRST: without it
        this test has two causes for one symptom — "the bus was never reached"
        and "the code chose not to fire" both arrive as an empty list, which is
        the exact ambiguity this branch keeps refusing to ship in product code.
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

        # Exactly the bytecode `from X import trigger` compiles to, so the
        # check cannot pass by a route the code under test does not take.
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
    """`push-templates` and `diff-templates` scanned a pre-.trinity layout.

    They matched `*.local.json` at the branch ROOT — a naming convention no
    citizen has used since `.trinity/` landed, so zero real matches were
    possible and `diff-templates` reported 16 branches of phantom drift. The
    live half (propagating templates into @spawn's scaffold sets) is kept.

    Mutation notes: leaving either verb silently performing its no-op, or
    retiring the spawn half along with the dead half.
    """

    def test_the_dead_handlers_are_out_of_the_live_tree(self):
        """Not importable is the point: a no-op nobody can call cannot be trusted."""
        handlers = _MEMORY_ROOT / "apps" / "handlers" / "templates"

        assert not (handlers / "pusher.py").exists()
        assert not (handlers / "differ.py").exists()

    def test_no_live_handler_still_scans_the_pre_trinity_layout(self):
        """The suffix scan is what made zero matches possible. It is gone everywhere."""
        live = (_MEMORY_ROOT / "apps").rglob("*.py")
        offenders = [
            path.name
            for path in live
            if '.endswith(".local.json")' in path.read_text(encoding="utf-8")
            or '.endswith(".observations.json")' in path.read_text(encoding="utf-8")
        ]

        assert offenders == []

    def test_the_park_keeps_them_with_the_measurement(self):
        """Never a casual delete — the record of WHY outlives the code.

        A TRACKED park, not `.archive/`. Patrick's fleet-wide ruling of
        2026-08-18 makes `.archive/` the disposal zone: gitignored, cleaned
        without warning, present in no clone. This build put them there first,
        which would have made this very assertion pass only on machines that
        happened to still have the files — the exact CI failure that produced
        the ruling. The park is where a record that must survive a clone lives.
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
        for verb in ("push-templates", "diff-templates"):
            assert templates.handle_command(verb, ["--dry-run"]) is True
            printed = capsys.readouterr().out
            assert "push" in printed.lower()

    def test_the_spawn_scaffold_lane_survives(self):
        assert hasattr(spawn_pusher, "push_to_spawn_templates")

    def test_template_status_reports_the_live_receipts(self, live_fleet):
        """The old status read a push log only the dead lane could ever move.

        Reads every citizen's receipt off disk, so it needs a real fleet.
        """
        status = template_bump.receipt_status()

        assert status["gold"] == template_bump.gold_versions()
        assert status["branches"], "no branch receipts read"
        assert all("branch" in row and "carries" in row for row in status["branches"])

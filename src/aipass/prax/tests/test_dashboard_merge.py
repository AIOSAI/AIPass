# =================== AIPass ====================
# Name: test_dashboard_merge.py
# Description: quick_status has many writers — none may delete another's key
# Version: 1.1.0
# Created: 2026-08-13
# Modified: 2026-10-03
# =============================================

"""Tests for apps/handlers/dashboard/status.py, refresh.py, operations.py, template_pusher.py and template_differ.py."""

# Regression cover for the 2026-08-12 quick_status clobber (@flow, DPLAN-0290 item 4).
#
# DASHBOARD.local.json's quick_status block has several writers. Each one used to
# build a fresh dict and assign it over the whole block, so every writer silently
# deleted the keys it did not know about. The owner saw the symptom on his devpulse
# card: 0 todos while local.json held 9. @flow fixed their push and found the
# mirror here — prax refresh drops their ``commons_mentions`` on every run.
#
# The invariant both sides now hold: **no writer deletes a key it did not write.**
#
# Second defect, same file: the calculator existed in THREE near-identical copies
# (status.py, refresh.py, operations.py) and only one had grown a guard for a
# list-shaped ``active_plans``. flow's section writes a list, so the two unguarded
# copies raise TypeError on it. The copies are the reason one guard was missing,
# so the drift is pinned shut here too.
#
# The handlers are bound at the top by import statement. The reload this file
# used to do was for conftest's sys.modules stubs, which are gone (prax, leg 14).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — load_dashboard and save_dashboard, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — create_fresh_dashboard, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — get_branch_paths, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — resolve_branch_path, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — refresh_all_dashboards, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — diff_dashboard_template, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — push_dashboard_template, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — get_template_status, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — _extract_flow_section, covered by tests/test_flow_section_contract.py
# seedgo: no-test-needed(through_the_command) — plugin refresh(), covered by tests/test_devpulse_dashboard_plugin.py
# seedgo: no-test-needed(dead_code) — _extract_ai_mail_section's block, which refresh pops before save and nothing reads
# seedgo: no-test-needed(json_structure) — the log_operation records of the refresh, push and diff, covered by that row

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.prax.apps.handlers.dashboard import operations as ops
from aipass.prax.apps.handlers.dashboard import refresh
from aipass.prax.apps.handlers.dashboard import status
from aipass.prax.apps.handlers.dashboard import template_differ as differ
from aipass.prax.apps.handlers.dashboard import template_pusher as pusher


# A key only @flow writes. prax must carry it through untouched.
FOREIGN = {"commons_mentions": 4}


def _seed_branch(tmp_path: Path, quick_status: dict, todos: int = 2) -> Path:
    """Build a branch dir with a dashboard, a local.json and an inbox."""
    branch = tmp_path / "prax"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".ai_mail.local").mkdir(parents=True)

    (branch / "DASHBOARD.local.json").write_text(
        json.dumps(
            {
                "branch": "PRAX",
                "quick_status": quick_status,
                "sections": {"flow": {"managed_by": "flow", "active_plans": 3}},
            }
        ),
        encoding="utf-8",
    )
    (branch / ".trinity" / "local.json").write_text(
        json.dumps({"todos": [{"task": f"t{i}"} for i in range(todos)]}), encoding="utf-8"
    )
    (branch / ".ai_mail.local" / "inbox.json").write_text(
        json.dumps({"messages": [{"status": "new"}, {"status": "opened"}]}), encoding="utf-8"
    )
    return branch


def _push_world(tmp_path: Path, monkeypatch, module, template: dict, branch: "Path | None"):
    """Point the pusher or the differ at a world under tmp_path and return it.

    The template file, the registry (naming ``branch``, or nothing when None),
    the repo root and the pusher's version file all live under tmp_path, so
    push_dashboard_template and diff_dashboard_template, the public doors, run
    for real on it (prax, leg 14: these tests used to call the private step).
    """
    template_file = tmp_path / "DASHBOARD.template.json"
    template_file.write_text(json.dumps(template), encoding="utf-8")
    registry = tmp_path / "AIPASS_REGISTRY.json"
    entries = [] if branch is None else [{"name": branch.name.upper(), "path": str(branch), "status": "active"}]
    registry.write_text(json.dumps({"branches": entries}), encoding="utf-8")
    monkeypatch.setattr(module, "TEMPLATE_FILE", template_file)
    monkeypatch.setattr(module, "AIPASS_REGISTRY", registry)
    monkeypatch.setattr(module, "_find_repo_root", lambda: tmp_path)
    if module is pusher:
        monkeypatch.setattr(pusher, "VERSION_FILE", tmp_path / ".dashboard_version.json")
    return module


def _read_quick_status(branch: Path) -> dict:
    return json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["quick_status"]


# ---------------------------------------------------------------------------
# Finding 1 — no writer deletes a key it did not write
# ---------------------------------------------------------------------------


class TestForeignKeysSurviveEveryWriter:
    """commons_mentions is flow's. Every prax write path must carry it through."""

    def test_merge_preserves_unknown_keys(self):
        merged = status.merge_quick_status(
            {"commons_mentions": 4, "new_mail": 9}, {"new_mail": 1, "summary": "1 new emails"}
        )
        assert merged["commons_mentions"] == 4

    def test_merge_lets_owned_keys_win(self):
        """Preserving foreign keys must not freeze prax's own counters."""
        merged = status.merge_quick_status({"new_mail": 9}, {"new_mail": 1})
        assert merged["new_mail"] == 1

    def test_merge_tolerates_missing_existing_block(self):
        assert status.merge_quick_status(None, {"new_mail": 0})["new_mail"] == 0

    def test_write_section_preserves_foreign_key(self, tmp_path):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        ops.write_section(branch, "memory", {"managed_by": "memory", "vectors_stored": 7})
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_update_section_preserves_foreign_key(self, tmp_path):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        ops.update_section(branch, "memory", {"managed_by": "memory"}, {}, status.calculate_quick_status)
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_preserves_foreign_key(self, tmp_path):
        """The live path: `drone @prax dashboard refresh @prax`."""
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_still_recomputes_owned_keys(self, tmp_path):
        """Preservation must not turn refresh into a no-op."""
        branch = _seed_branch(tmp_path, {"new_mail": 99, "todo_count": 99, **FOREIGN}, todos=2)
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        quick = _read_quick_status(branch)
        assert quick["todo_count"] == 2
        assert quick["new_mail"] == 1

    def test_canary_plain_assignment_drops_the_key(self):
        """Proof the assertions above can fail: replacing the block is the bug."""
        block = {"new_mail": 0, **FOREIGN}
        block = {"new_mail": 1, "summary": "1 new emails"}
        assert "commons_mentions" not in block


# ---------------------------------------------------------------------------
# Finding 2 — a flow-shaped section must not raise
# ---------------------------------------------------------------------------

# The LEGACY flow shape: active_plans as a list of plan dicts, active_count as
# the int. Retired by @flow's module 2.0.0 (2026-08-16) — both writers now publish
# an int — but dashboards written before that date carry this on disk until their
# next write, so the tolerance must survive.
FLOW_LIST_SECTION = {
    "flow": {
        "managed_by": "flow",
        "active_plans": [{"id": "FPLAN-0001"}, {"id": "FPLAN-0002"}],
        "active_count": 2,
    }
}


def _calculators():
    """Every entry point that computes a quick_status block."""
    return [
        ("status.calculate_quick_status", status.calculate_quick_status),
        ("refresh._calculate_quick_status", refresh._calculate_quick_status),
        ("operations._calculate_quick_status_standalone", ops._calculate_quick_status_standalone),
        ("template_pusher._calculate_quick_status", pusher._calculate_quick_status),
    ]


#: The parametrize table, built once at the moment the decorators below read it.
#: A table computed at collection time can come back EMPTY, and pytest reports an
#: empty parametrize as SKIPPED — five lines that ran nothing while the summary
#: stayed green. This is the whole point of the file: FOUR near-identical copies
#: of one calculator, and the drift between them is what lost the list guard. The
#: names are spelled out so a copy that is renamed, moved or deleted fails
#: collection loudly instead of quietly shrinking the table it is tested through.
CALCULATOR_NAMES = (
    "status.calculate_quick_status",
    "refresh._calculate_quick_status",
    "operations._calculate_quick_status_standalone",
    "template_pusher._calculate_quick_status",
)

CALCULATORS = _calculators()

assert len(CALCULATORS) == len(CALCULATOR_NAMES), (
    f"expected {len(CALCULATOR_NAMES)} quick_status calculators, collected {len(CALCULATORS)}"
)
assert tuple(name for name, _calc in CALCULATORS) == CALCULATOR_NAMES
assert all(callable(calc) for _name, calc in CALCULATORS)


class TestListShapedActivePlans:
    """flow's own section shape must not raise in any copy of the calculator."""

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_list_shape_does_not_raise(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc(FLOW_LIST_SECTION, branch)["active_plans"] == 2, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_int_shape_still_works(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({"flow": {"active_plans": 3}}, branch)["active_plans"] == 3, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_missing_flow_section_is_zero(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({}, branch)["active_plans"] == 0, name

    def test_every_calculator_agrees(self, tmp_path):
        """One calculation, four doors. Drift here is what lost the guard."""
        branch = _seed_branch(tmp_path, {})
        results = [calc(FLOW_LIST_SECTION, branch) for _name, calc in _calculators()]
        assert all(r == results[0] for r in results[1:])


# ---------------------------------------------------------------------------
# Finding 3 — push-template is a fourth writer, and it deletes on purpose
# ---------------------------------------------------------------------------


class TestPushTemplateIsNotAWreckingBall:
    """`dashboard push-template` writes every branch's dashboard, fleet-wide.

    It carried its own self-contained calculator (no todo_count, no merge) and a
    deprecation list naming ``commons_mentions`` — a key @flow OWNS and writes
    (``flow/apps/handlers/dashboard/push_branch_dashboard.py``). prax used to own
    that key and retired it; the list outlived the ownership change, so one push
    would have deleted flow's key from every branch by declared policy.
    """

    def test_commons_mentions_is_not_deprecated(self):
        assert "commons_mentions" not in pusher.DEPRECATED_QUICK_STATUS_KEYS

    def test_the_differ_reads_the_pushers_list_not_its_own_copy(self):
        """The adviser carried a second copy of the policy and kept recommending
        the deletion of flow's live key for weeks after the writer was fixed
        (docs/dashboard.md, 2026-08-25). One list, the pusher's, or the advice
        and the write disagree again."""
        assert differ.DEPRECATED_QUICK_STATUS_KEYS is pusher.DEPRECATED_QUICK_STATUS_KEYS
        assert "commons_mentions" not in differ.DEPRECATED_QUICK_STATUS_KEYS

    def test_structural_update_preserves_foreign_key(self, tmp_path, monkeypatch):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})

        result = _push_world(tmp_path, monkeypatch, pusher, {}, branch).push_dashboard_template(dry_run=False)

        assert result["branches_updated"] == 1
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_structural_update_keeps_todo_count(self, tmp_path, monkeypatch):
        """The pusher's own calculator had no todo_count at all, so it dropped it."""
        branch = _seed_branch(tmp_path, {"new_mail": 0, "todo_count": 99}, todos=2)

        _push_world(tmp_path, monkeypatch, pusher, {}, branch).push_dashboard_template(dry_run=False)

        assert _read_quick_status(branch)["todo_count"] == 2

    def test_structural_update_without_a_branch_stays_placeholder(self, tmp_path, monkeypatch):
        """spawn's builder template has no .trinity/ or inbox — it must not gain counts."""
        spawn_template = tmp_path / "src" / "aipass" / "spawn" / "templates" / "builder" / "DASHBOARD.local.json"
        spawn_template.parent.mkdir(parents=True)
        spawn_template.write_text(
            json.dumps({"quick_status": {}, "sections": {"flow": {"active_plans": 0}}}), encoding="utf-8"
        )

        _push_world(tmp_path, monkeypatch, pusher, {}, None).push_dashboard_template(dry_run=False)

        quick = json.loads(spawn_template.read_text(encoding="utf-8"))["quick_status"]
        assert quick["todo_count"] == 0
        assert quick["new_mail"] == 0

    def test_a_template_section_the_constant_never_heard_of_is_advised(self, tmp_path, monkeypatch):
        """The adviser's third copy of the policy.

        _diff_branch accepted the loaded template and compared against
        module-level REQUIRED_SECTIONS instead (seedgo's
        accepted_and_never_used_parameter rule, 2026-09-24). That copy happens to
        agree with templates/DASHBOARD.template.json today, so the drift would be
        silent both ways: a section added to the template would never be advised,
        and the advice would keep naming one the template had dropped.
        """
        branch = _seed_branch(tmp_path, {"new_mail": 0})
        template = {"sections": {"a_brand_new_section": {}}, "quick_status": {"new_mail": 0}}

        result = _push_world(tmp_path, monkeypatch, differ, template, branch).diff_dashboard_template("PRAX")

        assert "a_brand_new_section section" in result["branches"][0]["additions"]

    def test_canary_deprecation_list_still_deletes(self):
        """Proof the first assertion can fail: the removal loop is real."""
        qs = {"commons_mentions": 4, "pending_bulletins": 1}
        for key in ["pending_bulletins", "commons_mentions"]:
            qs.pop(key, None)
        assert qs == {}


# ---------------------------------------------------------------------------
# Finding 4 — action_required must agree with the summary beside it
# ---------------------------------------------------------------------------


class TestActionRequiredMatchesItsOwnSummary:
    """@flow measured prax writing ``action_required: False`` next to ``1 todos``.

    Identical counts, opposite flag from the two writers — the same clobber
    species as Finding 1, moved out of a key and into a boolean, and it is the
    field the owner's card reads for 'needs attention'.
    """

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_todos_alone_require_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=1)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["todo_count"] == 1, name
        assert result["action_required"] is True, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_all_clear_requires_no_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=0)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["summary"] == "All clear", name
        assert result["action_required"] is False, name

# =================== META ====================
# Name: test_ci_red.py
# Description: Tests for the ci_red event handler and medic's dispatch gates it runs
# Version: 1.0.0
# Created: 2026-10-23
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/events/ci_red.py and the dispatch gates it runs."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the poll, the replies and the push, in test_ci.py
# seedgo: no-test-needed(covered_elsewhere) — what should_dispatch and the breaker decide, in test_error_registry.py
# seedgo: no-test-needed(external) — ai_mail delivery and wake_branch; AIPass tests only its own files

import json

from aipass.trigger.apps.handlers.events.ci_red import handle_ci_red
from aipass.trigger.apps.modules.core import Trigger

LOG = (
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:48.3Z   hooks: 99%\n"
    "seedgo-audit\tRun seedgo standards audit\t2026-10-23T05:33:53.4Z ##[error]Process completed with exit code 1.\n"
)


def _fire(owner="hooks"):
    return Trigger.fire("ci_red", run_id=900, workflow="CI", step="audit", owner=owner, lines=["hooks: 99%"])


def _state(ci_lane, owner="hooks"):
    return ci_lane.ledger()["cures"][f"900@{owner}"]


def _suppressed(ci_lane):
    path = ci_lane.root / "logs" / "medic_suppressed.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestGates:
    def test_open_gates_mail_and_wake_the_owner(self, ci_lane):
        assert _fire()["ran"] == 1
        assert [m["to_branch"] for m in ci_lane.mails] == ["@hooks"]
        assert [w[0] for w in ci_lane.wakes] == ["@hooks"]
        assert _state(ci_lane)["state"] == "dispatched"

    def test_a_muted_owner_is_gated_and_the_refusal_logged(self, ci_lane):
        mute = {"config": {"muted_branches": [{"name": "hooks", "expires_at": None}]}}
        (ci_lane.root / "medic_state.json").write_text(json.dumps(mute), encoding="utf-8")
        _fire()
        assert ci_lane.mails == [] and _state(ci_lane)["state"] == "gated"
        assert _suppressed(ci_lane)[-1]["reason"].startswith("Branch muted")

    def test_medic_off_gates_the_dispatch(self, ci_lane):
        off = {"config": {"medic_enabled": False}}
        (ci_lane.root / "medic_state.json").write_text(json.dumps(off), encoding="utf-8")
        _fire()
        assert ci_lane.mails == [] and _state(ci_lane)["state"] == "gated"

    def test_an_unregistered_owner_is_gated(self, ci_lane):
        _fire(owner="ghost")
        assert ci_lane.mails == [] and _state(ci_lane, "ghost")["reason"] == "Unknown branch skipped: @ghost"

    def test_an_open_breaker_gates_the_dispatch(self, ci_lane):
        ci_lane.breaker_open = True
        _fire()
        assert ci_lane.mails == [] and "Circuit breaker" in _state(ci_lane)["reason"]

    def test_backoff_gates_the_dispatch(self, ci_lane):
        ci_lane.backoff = True
        _fire()
        assert ci_lane.mails == [] and "backing off" in _state(ci_lane)["reason"]

    def test_devpulse_as_owner_is_emailed_and_never_woken(self, ci_lane):
        _fire(owner="devpulse")
        assert [m["to_branch"] for m in ci_lane.mails] == ["@devpulse"]
        assert ci_lane.wakes == []
        assert _state(ci_lane, "devpulse")["state"] == "emailed"

    def test_the_red_is_fingerprinted_into_the_error_registry(self, ci_lane):
        _fire()
        registry = json.loads((ci_lane.root / "error_registry.json").read_text(encoding="utf-8"))
        [entry] = registry["errors"].values()
        assert entry["component"] == "hooks" and entry["error_type"] == "ci_red"
        assert _state(ci_lane)["fingerprint"] == entry["fingerprint"]


class TestHandFire:
    def test_a_bare_run_id_triages_itself_and_dispatches_the_owner(self, ci_lane):
        ci_lane.add_run("900")
        ci_lane.logs["900"] = LOG
        Trigger.fire("ci_red", run_id=900)
        [mail] = ci_lane.mails
        assert mail["to_branch"] == "@hooks" and "hooks: 99%" in mail["message"]
        cure = _state(ci_lane)
        assert cure["workflow"] == "CI" and cure["step"] == "Run seedgo standards audit"

    def test_a_fire_without_a_run_id_does_nothing(self, ci_lane):
        handle_ci_red(owner="hooks", lines=["x"])
        assert ci_lane.mails == [] and ci_lane.calls == []
        assert not (ci_lane.root / "ci_ledger.json").exists()

    def test_a_handler_failure_never_reaches_the_caller(self, ci_lane):
        (ci_lane.root / "ci_ledger.json").write_text("{torn", encoding="utf-8")
        assert _fire()["failed"] == 0
        assert "handle_ci_red failed" in (ci_lane.root / "ci_lane.jsonl").read_text(encoding="utf-8")

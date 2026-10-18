# =================== AIPass ====================
# Name: test_live_config_timeouts.py
# Version: 1.0.1
# Description: Pins against the live .aipass/hooks.json and .aipass/project_hooks.json
# Branch: hooks
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Tests for the live .aipass/ hook configs that apps/handlers/config/loader.py hands the engine."""

# Reads the REAL repo-root configs on purpose (a copied tree fails here); new live-config pins go here.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — _run_handler's timeout_s default of 30, owned by tests/test_engine.py
# seedgo: no-test-needed(stdlib) — json.loads reading the files; a malformed file fails every test here at once


class TestLiveProjectConfigTimeouts:
    """Pins the shipped .aipass/hooks.json, not a fixture.

    A UserPromptSubmit entry without a timeout key is killed at the hardcoded 30, output discarded.
    """

    @staticmethod
    def _live_ups():
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]
        config = json.loads((root / ".aipass" / "hooks.json").read_text(encoding="utf-8"))
        return {k: v for k, v in config["UserPromptSubmit"].items() if isinstance(v, dict)}

    def test_every_user_prompt_submit_hook_declares_a_timeout(self):
        missing = [name for name, defn in self._live_ups().items() if "timeout" not in defn]
        assert missing == [], f"these fall back to the hardcoded 30: {missing}"

    def test_no_user_prompt_submit_hook_sits_at_or_below_30(self):
        low = {n: d["timeout"] for n, d in self._live_ups().items() if d.get("timeout", 0) <= 30}
        assert low == {}, f"still inside the old ceiling: {low}"

    def test_auto_process_keeps_its_larger_allowance(self):
        """It is the handler that actually times out — measured up to 120.5s."""
        assert self._live_ups()["auto_process"]["timeout"] == 120


class TestTheProjectTemplateCarriesTheTestWriteGate:
    """Pins the shipped .aipass/project_hooks.json — what every NEW project inherits.

    The test-write gate is fleet-wide; a template can drop it while this tree stays green.
    """

    @staticmethod
    def _template_pretooluse():
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]
        config = json.loads((root / ".aipass" / "project_hooks.json").read_text(encoding="utf-8"))
        return config["PreToolUse"]

    def test_new_projects_inherit_the_gate(self):
        assert "testwrite_gate" in self._template_pretooluse(), (
            "a project stamped by `aipass init` would start without the fleet ruling"
        )

    def test_the_entry_points_at_the_real_handler(self):
        entry = self._template_pretooluse()["testwrite_gate"]
        assert entry["handler"] == "aipass.hooks.apps.handlers.security.testwrite_gate.handle"
        assert entry["enabled"] is True

    def test_the_matcher_covers_both_lanes(self):
        """The scripted lane is half the gate; a matcher without Bash silently halves it."""
        matcher = self._template_pretooluse()["testwrite_gate"]["matcher"].split("|")
        assert "Bash" in matcher
        for tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
            assert tool in matcher


class TestTheTemplateRuling:
    """Pins the 2026-09-09 ruling on .aipass/project_hooks.json (DPLAN-0335 leg 2).

    A shipped dotted path that resolves to nothing breaks every project `aipass init` stamps.
    """

    @staticmethod
    def _template():
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]
        return json.loads((root / ".aipass" / "project_hooks.json").read_text(encoding="utf-8"))

    @classmethod
    def _entries(cls):
        return {
            name: defn
            for event, hooks in cls._template().items()
            if isinstance(hooks, dict)
            for name, defn in hooks.items()
            if isinstance(defn, dict)
        }

    def test_every_template_handler_actually_imports(self):
        """The auto_watchdog cure, generalised: a shipped entry whose module or
        function does not exist is a hook every new project silently never gets."""
        import importlib

        broken = []
        for name, defn in self._entries().items():
            module_path, _, func = defn["handler"].rpartition(".")
            try:
                if not hasattr(importlib.import_module(module_path), func):
                    broken.append(f"{name}: {defn['handler']} (no attribute {func})")
            except ImportError as exc:
                broken.append(f"{name}: {defn['handler']} ({exc})")
        assert broken == [], f"template entries pointing at nothing: {broken}"

    def test_the_retired_watchdog_is_gone(self):
        assert "auto_watchdog" not in self._entries()

    def test_the_project_appropriate_handlers_are_all_present(self):
        """The ruling itself. Each was judged individually — docs/project_config.md,
        section 'The template ruling', carries the per-handler reason."""
        entries = self._entries()
        for name in (
            "temporal",
            "context_gauge",
            "persistent_alert",
            "pre_compact_prep",
            "post_compact_regrounding",
            "registry_gate",
            "feedback_pulse",
        ):
            assert name in entries, f"{name} was ruled project-appropriate and must ship"

    def test_the_framework_only_handlers_stay_out(self):
        """Silence here is the ruling too: each of these needs an AIPass-only
        service (@memory, the compass, the fleet seat rule, Telegram) a project lacks."""
        entries = self._entries()
        for name in (
            "presence_gate",
            "presence_release",
            "auto_process",
            "compass_recall",
            "user_message_relay",
            "telegram_response",
        ):
            assert name not in entries, f"{name} was ruled framework-only"

    def test_feedback_pulse_ships_switched_off(self):
        """Ruled project-appropriate, but a project opts IN to being asked."""
        assert self._entries()["feedback_pulse"]["enabled"] is False

    def test_the_scripted_lane_is_live_in_the_template(self):
        """A matcher without Bash is a fence only the tool lane can see.

        Without it, `sed -i` in every project `aipass init` creates bypasses the cross-project fence.
        """
        matcher = self._template()["PreToolUse"]["pre_edit_gate"]["matcher"]
        assert "Bash" in matcher.split("|"), f"the scripted lane is dark in the template: {matcher}"

    def test_release_notice_is_wired_on_session_start(self):
        entry = self._template()["SessionStart"]["release_notice"]
        assert entry["handler"] == "aipass.hooks.apps.handlers.lifecycle.release_notice.handle"
        assert entry["enabled"] is True

    def test_the_comment_records_where_the_ruling_lives(self):
        """A template that is not a mirror says so and names the page and section holding the table."""
        comment = self._template()["_comment"]
        assert "not a mirror" in comment
        assert "docs/project_config.md" in comment
        assert "The template ruling" in comment

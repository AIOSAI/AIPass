"""Pins against the live .aipass/ configs, not fixtures — see each class docstring.

Both classes here read the REAL repo-root files on purpose, which is why this
file is one of the four that red a copied tree in @seedgo's audit-tests control
run: measuring the live installation is the whole point, and a copy is not it.
New live-config pins belong HERE rather than in a fifth file, so that
position-dependence stays concentrated where it is declared.
"""


class TestLiveProjectConfigTimeouts:
    """Pins the shipped .aipass/hooks.json, not a fixture.

    UserPromptSubmit handlers ran on the hardcoded 30 because no entry carried a
    timeout key. Patrick hit a 30s kill with output discarded on 2026-08-13 21:22.
    These assert the config half of the stopgap is present in the file the engine
    actually reads — a fixture-based test would not have caught its absence.
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

    Patrick ruled the test-write gate fleet-wide on 2026-09-01 (DPLAN-0323).
    A template is the one place a fleet-wide ruling can be silently absent: the
    gate can be correct, wired and green in this tree while every project stamped
    tomorrow starts without it, and no suite that reads a fixture would notice.
    That is the same species as the timeout gap above — the config half missing
    while the code half is fine.
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

    The template had drifted 13 handlers behind the framework config and still
    shipped `auto_watchdog`, whose handler file had already been renamed to
    `auto_watchdog(disabled).py` — a dotted path in a shipped config resolving to
    nothing, in every project stamped since. Same species as the two classes
    above: the config half wrong while the code half is fine, and invisible to
    any test that reads a fixture instead of the file `aipass init` copies.
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
        function does not exist is a hook every new project silently never gets.
        Import is the only check that cannot be fooled by a plausible string."""
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
        """The ruling itself. Each was judged individually — README section
        'The template ruling' carries the per-handler reason."""
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
        service (@memory, the compass, the fleet seat rule, Telegram) that a
        project does not have, so shipping one buys a per-turn no-op at best."""
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

    def test_release_notice_is_wired_on_session_start(self):
        entry = self._template()["SessionStart"]["release_notice"]
        assert entry["handler"] == "aipass.hooks.apps.handlers.lifecycle.release_notice.handle"
        assert entry["enabled"] is True

    def test_the_comment_records_where_the_ruling_lives(self):
        """A config that silently stopped mirroring the framework file has to say
        so in the file itself, or the next reader re-derives the drift as a bug."""
        comment = self._template()["_comment"]
        assert "RULING 2026-09-09" in comment
        assert "README.md" in comment

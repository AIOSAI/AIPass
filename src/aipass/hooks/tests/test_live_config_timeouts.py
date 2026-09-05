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

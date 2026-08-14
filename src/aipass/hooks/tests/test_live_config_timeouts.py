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

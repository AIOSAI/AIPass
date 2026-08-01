# =================== AIPass ====================
# Name: test_post_compact_regrounding.py
# Version: 1.0.0
# Description: Tests for post_compact_regrounding lifecycle handler (DPLAN-0276)
# Branch: hooks
# Created: 2026-08-01
# Modified: 2026-08-01
# =============================================

"""Tests for handlers/lifecycle/post_compact_regrounding.py.

Replays the DPLAN-0276 incident: PreCompact can fire several times back-to-back
with no intervening UserPromptSubmit, so cadence's normal turn-0 grounding path
never runs. This PostToolUse backstop must inject grounding content directly via
additionalContext the next time any tool runs, exactly once per compact, and
stay silent otherwise.
"""

import json
from unittest.mock import patch


class TestPostCompactRegrounding:
    def test_silent_when_nothing_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=False):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_injects_all_sections_when_pending(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value="BRANCH"),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert result["sound"] == "post compact reground"
        payload = json.loads(result["stdout"])
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        context = payload["hookSpecificOutput"]["additionalContext"]
        assert "KERNEL" in context
        assert "NAVMAP" in context
        assert "BRANCH" in context
        assert "IDENTITY" in context
        assert "DPLAN-0276" in context

    def test_silent_when_pending_but_all_content_empty(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value=""),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_one_loader_failing_does_not_block_the_others(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with (
            patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", return_value=True),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", side_effect=OSError("boom")),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value=""),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        payload = json.loads(result["stdout"])
        context = payload["hookSpecificOutput"]["additionalContext"]
        assert "NAVMAP" in context
        assert "IDENTITY" in context

    def test_cadence_check_failure_is_silent(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding

        with patch("aipass.hooks.apps.modules.cadence.consume_regroup_pending", side_effect=RuntimeError("boom")):
            result = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}

    def test_end_to_end_replays_incident_multiple_resets_one_fire(self, tmp_path):
        """No mocking of cadence: several PreCompact resets fire back-to-back
        (the actual incident pattern), then the next tool call must reground
        exactly once and stay silent after that."""
        from aipass.hooks.apps.handlers.lifecycle import post_compact_regrounding
        from aipass.hooks.apps.modules import cadence

        cadence._turn = None
        cadence._config = None

        with (
            patch("aipass.hooks.apps.modules.cadence._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "incident-session"}),
            patch("aipass.hooks.apps.modules.grounding_content.load_kernel", return_value="KERNEL"),
            patch("aipass.hooks.apps.modules.grounding_content.load_navmap", return_value="NAVMAP"),
            patch("aipass.hooks.apps.modules.grounding_content.load_branch", return_value="BRANCH"),
            patch("aipass.hooks.apps.modules.grounding_content.load_identity", return_value="IDENTITY"),
        ):
            cadence.reset_counter()
            cadence.reset_counter()
            cadence.reset_counter()

            first = post_compact_regrounding.handle({"cwd": str(tmp_path)})
            second = post_compact_regrounding.handle({"cwd": str(tmp_path)})

        assert "KERNEL" in first["stdout"]
        assert second == {"stdout": "", "exit_code": 0}

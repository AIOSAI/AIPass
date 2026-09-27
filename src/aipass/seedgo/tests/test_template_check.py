# =================== META ====================
# Name: test_template_check.py
# Description: Unit tests for template_check
# Version: 1.2.0
# Created: 2026-07-01
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/template_check.py, the template/boilerplate detection checker."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that template_check.py parses and imports
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py

import json

import pytest
from unittest.mock import MagicMock

from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils
from aipass.seedgo.apps.handlers.aipass_standards.template_check import check_branch


def _prompt_check(tmp_path, content):
    """check_branch's verdict on a branch prompt holding `content` (markdown, curly braces scanned)."""
    prompt = tmp_path / ".aipass"
    prompt.mkdir()
    (prompt / "aipass_local_prompt.md").write_text(content, encoding="utf-8")
    result = check_branch(str(tmp_path))
    return next(c for c in result["checks"] if c["name"] == "aipass_local_prompt.md")


def _passport_check(tmp_path, content):
    """check_branch's verdict on a passport holding `content` (not markdown, curly braces not scanned)."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    (trinity / "passport.json").write_text(content, encoding="utf-8")
    result = check_branch(str(tmp_path))
    return next(c for c in result["checks"] if c["name"] == "passport.json")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here.

    The bypass tests call the real is_bypassed, which appends to the
    repo-tracked seedgo_json/utils_log.json via the json_handler global in
    its OWN module -- xdist workers racing on that shared file corrupt it
    (JSONDecodeError: Extra data). sys.modules patching never reaches a
    function's globals, so the pin must land on the utils module object.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


# ===========================================================================
# 1. Marker detection — through check_branch
# ===========================================================================


class TestFindMarkers:
    """Marker detection, reached through check_branch on a prompt or a passport."""

    def test_needs_configuration_detected(self, tmp_path):
        """Mutant: NEEDS CONFIGURATION dropped from _DEFINITIVE_MARKERS in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "This file NEEDS CONFIGURATION.")
        assert "NEEDS CONFIGURATION" in check["message"]

    def test_mustache_branchname_detected(self, tmp_path):
        """Mutant: {{BRANCHNAME}} dropped from _DEFINITIVE_MARKERS in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "Welcome to {{BRANCHNAME}}.")
        assert "{{BRANCHNAME}}" in check["message"]

    def test_mustache_branch_detected(self, tmp_path):
        """Mutant: {{BRANCH}} dropped from _DEFINITIVE_MARKERS in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "Branch: {{BRANCH}}")
        assert "{{BRANCH}}" in check["message"]

    def test_instructions_marker_detected(self, tmp_path):
        """Mutant: the INSTRUCTIONS marker dropped from _DEFINITIVE_MARKERS in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE")
        assert check["passed"] is False

    def test_when_youre_done_detected(self, tmp_path):
        """Mutant: WHEN YOU'RE DONE dropped from _DEFINITIVE_MARKERS in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "WHEN YOU'RE DONE, delete this section")
        assert "WHEN YOU'RE DONE" in check["message"]

    def test_single_curly_detected_in_markdown(self, tmp_path):
        """Mutant: the single-curly scan disabled in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _prompt_check(tmp_path, "Role: {one-line role description}\nDo: {Primary responsibility}")
        assert "single-curly" in check["message"]

    def test_single_curly_not_detected_in_json(self, tmp_path):
        """Mutant: the single-curly scan run on every file in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, '{"key": "value", "nested": {"a": 1}}')
        assert "single-curly" not in check["message"]

    def test_double_curly_not_double_counted_as_single(self, tmp_path):
        """Mutant: double curlies no longer stripped before the single-curly scan in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _prompt_check(tmp_path, "Hello {{BRANCH}}, welcome.")
        assert "single-curly" not in check["message"]

    def test_clean_content_no_markers(self, tmp_path):
        """Mutant: _find_markers starts with a spurious marker in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _prompt_check(tmp_path, "This is a well-configured branch prompt with real content.")
        assert check["passed"] is True
        assert check["message"] == "no template markers"

    def test_case_insensitive_detection(self, tmp_path):
        """Mutant: markers matched case-sensitively in apps/handlers/aipass_standards/template_check.py — killed."""
        check = _passport_check(tmp_path, "needs configuration")
        assert "NEEDS CONFIGURATION" in check["message"]


# ===========================================================================
# 2. check_branch — integration tests
# ===========================================================================


class TestCheckBranch:
    """Tests for the check_branch function."""

    def test_stub_prompt_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(
            "# {{BRANCHNAME}}\nNEEDS CONFIGURATION\n"
            "INSTRUCTIONS FOR FILLING OUT THIS TEMPLATE\n"
            "WHEN YOU'RE DONE, delete this block.\n"
            "Role: {one-line role description}\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("# My Branch\nConfigured.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text('{"branch": "test"}', encoding="utf-8")

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["score"] < 100
        prompt_check = next(c for c in result["checks"] if "aipass_local_prompt" in c["name"])
        assert not prompt_check["passed"]
        assert "template markers" in prompt_check["message"]

    def test_configured_branch_clean(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(
            "# My Branch\nThis is my real prompt with real content.", encoding="utf-8"
        )
        (tmp_path / "README.md").write_text("# My Branch\nReal documentation.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"branch": "test", "role": "builder"}), encoding="utf-8")

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100
        assert all(c["passed"] for c in result["checks"])

    def test_bypass_suppresses_warning(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("NEEDS CONFIGURATION\n{{BRANCH}}\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Configured\nReal content.", encoding="utf-8")

        bypass_rules = [
            {
                "file": "aipass_local_prompt",
                "standard": "template",
                "reason": "intentionally left as template",
            }
        ]
        result = check_branch(str(tmp_path), bypass_rules=bypass_rules)
        prompt_check = next(c for c in result["checks"] if "aipass_local_prompt" in c["name"])
        assert prompt_check["passed"]
        assert "bypassed" in prompt_check["message"]

    def test_trinity_json_no_false_positive(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Branch\nReal docs.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "test"},
                    "identity": {"role": "builder", "purpose": "testing"},
                    "nested": {"key": "value"},
                }
            ),
            encoding="utf-8",
        )
        (trinity / "local.json").write_text(
            json.dumps(
                {
                    "sessions": [{"date": "2026-01-01", "summary": "work"}],
                    "todos": [],
                }
            ),
            encoding="utf-8",
        )

        result = check_branch(str(tmp_path))
        assert result["score"] == 100
        trinity_checks = [c for c in result["checks"] if c["name"].endswith(".json")]
        assert all(c["passed"] for c in trinity_checks)

    def test_trinity_memory_prose_not_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Branch\nReal docs.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"branch": "test"}), encoding="utf-8")
        (trinity / "local.json").write_text(
            json.dumps({"key_learnings": [{"value": "Detects NEEDS CONFIGURATION + mustache + curly placeholders"}]}),
            encoding="utf-8",
        )
        (trinity / "observations.json").write_text(
            json.dumps({"observations": [{"note": "template_pusher restoring {{BRANCHNAME}}"}]}),
            encoding="utf-8",
        )

        result = check_branch(str(tmp_path))
        assert result["score"] == 100

    def test_trinity_passport_with_markers_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Branch\nReal docs.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(
            json.dumps({"branch": "{{BRANCHNAME}}", "role": "NEEDS CONFIGURATION"}), encoding="utf-8"
        )

        result = check_branch(str(tmp_path))
        assert result["score"] < 100
        passport_check = next(c for c in result["checks"] if "passport" in c["name"])
        assert not passport_check["passed"]
        assert "template markers" in passport_check["message"]

    def test_standard_level_bypass(self, tmp_path):
        bypass_rules = [{"standard": "template", "reason": "skip all"}]
        result = check_branch(str(tmp_path), bypass_rules=bypass_rules)
        assert result["passed"] is True
        assert result["score"] == 100

    def test_missing_targets_skipped(self, tmp_path):
        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["advisory"] is True

    def test_readme_code_braces_not_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text(
            "# Branch\n\nExample:\n```python\nwrite_section(data, {'new': 3, 'total': 5})\n```\n"
            "Use `apps/plugins/{name}/` for plugins.\n",
            encoding="utf-8",
        )

        result = check_branch(str(tmp_path))
        readme_check = next(c for c in result["checks"] if c["name"] == "README.md")
        assert readme_check["passed"]

    def test_prompt_code_fence_braces_not_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(
            "Real configured prompt.\n\n```python\nprint(f'Error: {e}')\nresult = {k: v}\n```\n"
            "Also `{inline_code}` is fine.\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("# Branch\nConfigured.", encoding="utf-8")

        result = check_branch(str(tmp_path))
        prompt_check = next(c for c in result["checks"] if "aipass_local_prompt" in c["name"])
        assert prompt_check["passed"]

    def test_curly_placeholders_in_prompt(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(
            "Role: {one-line role description}\nDo: {Primary responsibility}\nCommands: {command1}\n",
            encoding="utf-8",
        )
        (tmp_path / "README.md").write_text("# Branch\nConfigured.", encoding="utf-8")

        result = check_branch(str(tmp_path))
        prompt_check = next(c for c in result["checks"] if "aipass_local_prompt" in c["name"])
        assert not prompt_check["passed"]
        assert "single-curly" in prompt_check["message"]

    def test_readme_definitive_marker_in_code_not_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text(
            "# Spawn\n\nReal docs.\n\n"
            "4. **Rename** — Replace `{{BRANCH}}` in directory names\n\n"
            "```bash\nmv {{BRANCHNAME}} my-branch\n```\n",
            encoding="utf-8",
        )

        result = check_branch(str(tmp_path))
        readme_check = next(c for c in result["checks"] if c["name"] == "README.md")
        assert readme_check["passed"]

    def test_md_definitive_marker_in_prose_still_flagged(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text(
            "# {{BRANCHNAME}} — Branch Prompt\nNEEDS CONFIGURATION\n", encoding="utf-8"
        )
        (tmp_path / "README.md").write_text("# Branch\nConfigured.", encoding="utf-8")

        result = check_branch(str(tmp_path))
        prompt_check = next(c for c in result["checks"] if "aipass_local_prompt" in c["name"])
        assert not prompt_check["passed"]
        assert "{{BRANCHNAME}}" in prompt_check["message"]
        assert "NEEDS CONFIGURATION" in prompt_check["message"]

    def test_passport_json_markers_not_code_stripped(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "aipass_local_prompt.md").write_text("Real prompt.", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Branch\nReal docs.", encoding="utf-8")
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(
            json.dumps({"branch": "{{BRANCHNAME}}", "role": "test"}), encoding="utf-8"
        )

        result = check_branch(str(tmp_path))
        passport_check = next(c for c in result["checks"] if "passport" in c["name"])
        assert not passport_check["passed"]
        assert "{{BRANCHNAME}}" in passport_check["message"]

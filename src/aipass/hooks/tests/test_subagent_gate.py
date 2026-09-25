# =================== AIPass ====================
# Name: test_subagent_gate.py
# Version: 1.0.0
# Description: Tests for subagent_gate security handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Tests for handlers/security/subagent_gate.py."""

import json
from unittest.mock import patch, MagicMock

from aipass.hooks.apps.handlers.security.subagent_gate import handle


class TestSubagentGateHandler:
    def test_no_repo_root_allows(self):
        with patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root", return_value=None):
            result = handle({"agent_type": "general-purpose", "cwd": "/fake/nowhere"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_no_modified_files_allows(self):
        with patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root", return_value=None):
            result = handle({"agent_type": "general-purpose", "cwd": "/fake/somewhere"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability", return_value=None)
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_modified_files_no_violations_allows(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = ["/fake/repo/src/aipass/hooks/apps/test.py"]
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability", return_value=None)
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_violations_blocks(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = ["/fake/repo/src/aipass/hooks/apps/bad.py"]
        mock_seedgo.return_value = ["Missing docstring", "No tests"]
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Missing docstring" in parsed["reason"]
        assert "No tests" in parsed["reason"]
        assert "bad.py" in parsed["reason"]
        assert result["sound"] == "subagent gate"

    @patch("subprocess.run")
    def test_skip_claude_hooks_from_modified_files(self, mock_run, tmp_path):

        src = tmp_path / "src" / "aipass" / "hooks"
        src.mkdir(parents=True)
        (tmp_path / ".git").mkdir()
        mock_run.return_value = MagicMock(stdout=" M .claude/hooks/something.py\n", returncode=0)
        with patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root", return_value=tmp_path):
            with patch("aipass.hooks.apps.handlers.security.subagent_gate._get_cwd_branch", return_value="hooks"):
                from aipass.hooks.apps.handlers.security.subagent_gate import _get_modified_py_files

                files = _get_modified_py_files(str(src), tmp_path)
        assert files == []

    @patch("subprocess.run")
    def test_skip_claude_hooks_from_seedgo_checks(self, mock_run):
        from pathlib import Path
        from aipass.hooks.apps.handlers.security.subagent_gate import _run_seedgo_checklist

        result = _run_seedgo_checklist("/repo/.claude/hooks/gate.py", Path("/repo"))
        assert result == []
        mock_run.assert_not_called()

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_readme_accountability_advisory(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = ["/fake/repo/src/aipass/hooks/apps/clean.py"]
        mock_readme.return_value = (
            "Hook files were modified but .claude/hooks/README.md was not updated. "
            "Consider updating the README to reflect your changes."
        )
        result = handle({"agent_type": "Explore", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 0
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "allow"
        assert "README" in parsed["reason"]
        assert "sound" not in result

    def test_empty_hook_data_allows(self):
        result = handle({})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_empty_agent_type_skips_heavy_work(self):
        """Internal CC turns (empty agent_type) skip drone @git status + seedgo."""
        with patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root") as mock_root:
            result = handle({"agent_type": "", "cwd": "/fake/repo"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        mock_root.assert_not_called()

    def test_missing_agent_type_skips_heavy_work(self):
        """Missing agent_type key treated same as empty — skip."""
        with patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root") as mock_root:
            result = handle({"cwd": "/fake/repo"})
        assert result["exit_code"] == 0
        mock_root.assert_not_called()

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability", return_value=None)
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_real_agent_type_runs_full_check(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        """Real sub-agents (non-empty agent_type) get the full seedgo check."""
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = ["/fake/repo/src/aipass/hooks/apps/bad.py"]
        mock_seedgo.return_value = ["Missing docstring"]
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 2
        mock_root.assert_called_once()
        mock_seedgo.assert_called_once()

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_exception_in_get_modified_allows(self, mock_root, mock_modified):
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.side_effect = RuntimeError("subprocess died")
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result


class TestSubagentGateExternalProject:
    """Verify subagent gate works for non-AIPass projects (e.g. src/vera_studio/)."""

    def test_get_cwd_branch_external_package(self, tmp_path):
        from aipass.hooks.apps.handlers.security.subagent_gate import _get_cwd_branch

        # Use tmp_path for OS-native, drive-anchored paths — synthetic POSIX
        # strings break on Windows where .resolve() anchors to the current drive.
        repo_root = tmp_path / "vera"
        cwd = repo_root / "src" / "vera_studio" / "quality"
        cwd.mkdir(parents=True)
        branch = _get_cwd_branch(str(cwd), repo_root)
        assert branch == "quality"

    def test_get_cwd_branch_aipass_still_works(self, tmp_path):
        from aipass.hooks.apps.handlers.security.subagent_gate import _get_cwd_branch

        repo_root = tmp_path / "AIPass"
        cwd = repo_root / "src" / "aipass" / "hooks"
        cwd.mkdir(parents=True)
        branch = _get_cwd_branch(str(cwd), repo_root)
        assert branch == "hooks"

    def test_get_package_from_cwd_external(self):
        from aipass.hooks.apps.handlers.security.subagent_gate import _get_package_from_cwd

        assert _get_package_from_cwd("/fake/projects/vera/src/vera_studio/quality") == "vera_studio"
        assert _get_package_from_cwd("/fake/projects/AIPass/src/aipass/hooks") == "aipass"
        assert _get_package_from_cwd("/fake/no-src-here") == ""

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability", return_value=None)
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_violations_block_external_project(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        from pathlib import Path

        mock_root.return_value = Path("/fake/vera")
        mock_modified.return_value = ["/fake/vera/src/vera_studio/quality/apps/bad.py"]
        mock_seedgo.return_value = ["Missing docstring"]
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/vera/src/vera_studio/quality"})
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Missing docstring" in parsed["reason"]
        assert result["sound"] == "subagent gate"

    @patch("aipass.hooks.apps.handlers.security.subagent_gate._check_hook_readme_accountability", return_value=None)
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._run_seedgo_checklist", return_value=[])
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._get_modified_py_files")
    @patch("aipass.hooks.apps.handlers.security.subagent_gate._find_repo_root")
    def test_clean_files_allow_external_project(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        from pathlib import Path

        mock_root.return_value = Path("/fake/vera")
        mock_modified.return_value = ["/fake/vera/src/vera_studio/quality/apps/clean.py"]
        result = handle({"agent_type": "Explore", "cwd": "/fake/vera/src/vera_studio/quality"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result


_GATE = "aipass.hooks.apps.handlers.security.subagent_gate"


class TestSubagentGateBudget:
    """The engine kills this hook at 60s; the gate must finish inside it on its own terms.

    Measured 2026-09-25 01:49:59: 60,002ms in @devpulse's tree, 20 timeouts since
    08-13. One `drone @seedgo checklist` per modified file, serially, 15s each,
    with no total budget: four slow files and the engine kills the whole gate,
    so nothing is reported at all. And one checklist timeout used to fall into
    the outer except and abandon every file after it.
    """

    @patch(f"{_GATE}._check_hook_readme_accountability", return_value=None)
    @patch(f"{_GATE}._run_seedgo_checklist", return_value=[])
    @patch(f"{_GATE}._get_modified_py_files")
    @patch(f"{_GATE}._find_repo_root")
    def test_stops_checking_when_the_budget_is_spent(self, mock_root, mock_modified, mock_seedgo, mock_readme, caplog):
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = [f"/fake/repo/src/aipass/hooks/apps/f{i}.py" for i in range(8)]
        ticks = iter(range(0, 1000, 12))
        with patch(f"{_GATE}.time.monotonic", side_effect=lambda: next(ticks)):
            result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 0
        assert mock_seedgo.call_count < 8
        assert "unchecked" in caplog.text

    @patch(f"{_GATE}._check_hook_readme_accountability", return_value=None)
    @patch(f"{_GATE}._run_seedgo_checklist")
    @patch(f"{_GATE}._get_modified_py_files")
    @patch(f"{_GATE}._find_repo_root")
    def test_one_checklist_timeout_does_not_abandon_the_rest(self, mock_root, mock_modified, mock_seedgo, mock_readme):
        import subprocess
        from pathlib import Path

        mock_root.return_value = Path("/fake/repo")
        mock_modified.return_value = [
            "/fake/repo/src/aipass/hooks/apps/slow.py",
            "/fake/repo/src/aipass/hooks/apps/bad.py",
        ]
        mock_seedgo.side_effect = [subprocess.TimeoutExpired(cmd="drone", timeout=15), ["Missing docstring"]]
        result = handle({"agent_type": "general-purpose", "cwd": "/fake/repo/src/aipass/hooks"})
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "bad.py" in reason
        assert "slow.py" in reason

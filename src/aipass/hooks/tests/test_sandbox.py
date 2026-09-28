# =================== AIPass ====================
# Name: test_sandbox.py
# Version: 1.0.1
# Description: Tests for sandbox wrapper module
# Branch: hooks
# Created: 2026-06-09
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/sandbox.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that sandbox.py parses and every import resolves
# seedgo: no-test-needed(documentation) — that build_policy and sandbox_launch carry docstrings
# seedgo: no-test-needed(constant) — HELP_COMMANDS' display text and the CONSOLE binding
# seedgo: no-test-needed(stdlib) — shutil.which and tempfile.gettempdir's own path-resolution correctness

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.modules.sandbox import (
    _find_node,
    _find_rg,
    _srt_resolve_cwd,
    build_policy,
    build_srt_config,
    handle_command,
    resolve_bwrap_command,
    sandbox_launch,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="sandbox is Linux-only: bwrap mount namespaces")


class TestBuildSrtConfig:
    """Config generation from policy dict."""

    def test_minimal_policy(self, tmp_path):
        with patch("aipass.hooks.apps.modules.sandbox._find_rg", return_value="/usr/bin/rg"):
            config = build_srt_config({"allow_write": [str(tmp_path)]})

        assert config["network"] == {"allowAllUnixSockets": True}
        assert config["filesystem"]["allowWrite"] == [str(tmp_path)]
        assert config["filesystem"]["denyRead"] == []
        assert config["filesystem"]["denyWrite"] == []
        assert config["ripgrep"]["command"] == "/usr/bin/rg"

    def test_full_policy(self, tmp_path):
        write_root = tmp_path / "branch"
        policy = {
            "allow_write": [str(tmp_path), str(write_root)],
            "deny_write": [str(write_root / ".git")],
            "deny_read": ["/etc/shadow"],
        }
        with patch("aipass.hooks.apps.modules.sandbox._find_rg", return_value="/usr/bin/rg"):
            config = build_srt_config(policy)

        assert config["filesystem"]["allowWrite"] == [str(tmp_path), str(write_root)]
        assert config["filesystem"]["denyWrite"] == [str(write_root / ".git")]
        assert config["filesystem"]["denyRead"] == ["/etc/shadow"]

    def test_paths_stringified(self, tmp_path):
        policy = {"allow_write": [tmp_path, tmp_path / "home_like"]}
        with patch("aipass.hooks.apps.modules.sandbox._find_rg", return_value="/usr/bin/rg"):
            config = build_srt_config(policy)

        assert all(isinstance(p, str) for p in config["filesystem"]["allowWrite"])

    def test_missing_allow_write_raises(self):
        with (
            patch("aipass.hooks.apps.modules.sandbox._find_rg", return_value="/usr/bin/rg"),
            pytest.raises(KeyError),
        ):
            build_srt_config({})


class TestFindNode:
    """Node.js binary discovery."""

    def test_finds_node_on_path(self):
        with patch("aipass.hooks.apps.modules.sandbox.shutil.which", return_value="/usr/bin/node"):
            assert _find_node() == "/usr/bin/node"

    def test_raises_when_not_found(self):
        with (
            patch("aipass.hooks.apps.modules.sandbox.shutil.which", return_value=None),
            pytest.raises(FileNotFoundError, match="node not found"),
        ):
            _find_node()


class TestFindRg:
    """Ripgrep binary discovery."""

    def test_finds_rg_on_path(self):
        with patch("aipass.hooks.apps.modules.sandbox.shutil.which", return_value="/usr/bin/rg"):
            assert _find_rg() == "/usr/bin/rg"

    def test_falls_back_to_local_bin(self, tmp_path):
        fake_rg = tmp_path / ".local" / "bin" / "rg"
        fake_rg.parent.mkdir(parents=True)
        fake_rg.touch()

        with (
            patch("aipass.hooks.apps.modules.sandbox.shutil.which", return_value=None),
            patch("aipass.hooks.apps.modules.sandbox.Path.home", return_value=tmp_path),
        ):
            assert _find_rg() == str(fake_rg)

    def test_raises_when_not_found(self, tmp_path):
        with (
            patch("aipass.hooks.apps.modules.sandbox.shutil.which", return_value=None),
            patch("aipass.hooks.apps.modules.sandbox.Path.home", return_value=tmp_path),
            pytest.raises(FileNotFoundError, match="ripgrep"),
        ):
            _find_rg()


class TestResolveBwrapCommand:
    """Bwrap command resolution via Node helper."""

    def test_returns_bwrap_string(self):
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "bwrap --ro-bind / / -- /bin/bash -c 'echo hello'"
        fake_result.stderr = ""

        with (
            patch("aipass.hooks.apps.modules.sandbox._find_node", return_value="/usr/bin/node"),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.run", return_value=fake_result),
        ):
            cmd = resolve_bwrap_command("echo hello", {"network": {}})

        assert "bwrap" in cmd

    def test_raises_on_nonzero_exit(self):
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = ""
        fake_result.stderr = "some error"

        with (
            patch("aipass.hooks.apps.modules.sandbox._find_node", return_value="/usr/bin/node"),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.run", return_value=fake_result),
            pytest.raises(RuntimeError, match="srt resolve failed"),
        ):
            resolve_bwrap_command("echo hello", {"network": {}})

    def test_raises_on_empty_output(self):
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = ""
        fake_result.stderr = ""

        with (
            patch("aipass.hooks.apps.modules.sandbox._find_node", return_value="/usr/bin/node"),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.run", return_value=fake_result),
            pytest.raises(RuntimeError, match="empty command"),
        ):
            resolve_bwrap_command("echo hello", {"network": {}})

    def test_resolver_cwd_is_not_branch_dir(self):
        """srt resolves DANGEROUS_FILES relative to CWD. Using /var/tmp (or
        fallback) prevents mount-point pollution in the branch directory."""
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "bwrap --test"
        fake_result.stderr = ""

        captured_kwargs = {}

        def capture_run(args, **kwargs):
            captured_kwargs.update(kwargs)
            return fake_result

        with (
            patch("aipass.hooks.apps.modules.sandbox._find_node", return_value="/usr/bin/node"),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.run", side_effect=capture_run),
        ):
            resolve_bwrap_command("echo hello", {"network": {}})

        cwd = captured_kwargs.get("cwd", "")
        assert cwd and not cwd.startswith(str(Path.cwd()))

    def test_cleans_up_temp_file(self, tmp_path):
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "bwrap --test"
        fake_result.stderr = ""

        created_files = []

        def capture_run(args, **kwargs):
            config_path = args[2]
            created_files.append(config_path)
            return fake_result

        with (
            patch("aipass.hooks.apps.modules.sandbox._find_node", return_value="/usr/bin/node"),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.run", side_effect=capture_run),
        ):
            resolve_bwrap_command("echo hello", {"network": {}})

        assert len(created_files) == 1
        assert not Path(created_files[0]).exists()


class TestSandboxLaunch:
    """Full launch flow (mocked resolver)."""

    def test_returns_popen(self, tmp_path):
        fake_popen = MagicMock()

        with (
            patch(
                "aipass.hooks.apps.modules.sandbox.resolve_bwrap_command",
                return_value="bwrap --test -- /bin/bash -c 'echo hi'",
            ),
            patch(
                "aipass.hooks.apps.modules.sandbox.build_srt_config",
                return_value={"network": {}},
            ),
            patch(
                "aipass.hooks.apps.modules.sandbox.subprocess.Popen",
                return_value=fake_popen,
            ) as mock_popen,
        ):
            result = sandbox_launch("echo hi", policy={"allow_write": [str(tmp_path)]})

        assert result is fake_popen
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["/bin/bash", "-c", "bwrap --test -- /bin/bash -c 'echo hi'"]

    def test_passes_cwd(self, tmp_path):
        launch_cwd = tmp_path / "test"

        with (
            patch(
                "aipass.hooks.apps.modules.sandbox.resolve_bwrap_command",
                return_value="bwrap --test",
            ),
            patch(
                "aipass.hooks.apps.modules.sandbox.build_srt_config",
                return_value={"network": {}},
            ),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.Popen") as mock_popen,
        ):
            sandbox_launch("echo hi", cwd=str(launch_cwd), policy={"allow_write": [str(tmp_path)]})

        assert mock_popen.call_args[1]["cwd"] == str(launch_cwd)

    def test_passes_custom_env(self, tmp_path):
        custom_env = {"PATH": "/usr/bin", "HOME": str(tmp_path)}

        with (
            patch(
                "aipass.hooks.apps.modules.sandbox.resolve_bwrap_command",
                return_value="bwrap --test",
            ),
            patch(
                "aipass.hooks.apps.modules.sandbox.build_srt_config",
                return_value={"network": {}},
            ),
            patch("aipass.hooks.apps.modules.sandbox.subprocess.Popen") as mock_popen,
        ):
            sandbox_launch("echo hi", policy={"allow_write": [str(tmp_path)]}, env=custom_env)

        assert mock_popen.call_args[1]["env"] is custom_env


class TestSrtResolveCwd:
    """CWD selection for srt resolver — prevents mask-placeholder pollution."""

    def test_returns_var_tmp_when_available(self):
        mock_var = MagicMock()
        mock_var.is_dir.return_value = True
        mock_var.__str__ = MagicMock(return_value="/var/tmp")
        with patch("aipass.hooks.apps.modules.sandbox._VAR_TMP", mock_var):
            assert _srt_resolve_cwd() == "/var/tmp"

    def test_falls_back_to_tempdir(self, tmp_path):
        with (
            patch("aipass.hooks.apps.modules.sandbox._VAR_TMP") as mock_var,
            patch("aipass.hooks.apps.modules.sandbox.tempfile.gettempdir", return_value=str(tmp_path)),
        ):
            mock_var.is_dir.return_value = False
            assert _srt_resolve_cwd() == str(tmp_path)


class TestBuildPolicy:
    """Policy generation from branch path."""

    def _make_branch(self, tmp_path, name, citizen_class="builder", is_devpulse=False):
        """Create a minimal branch structure for testing."""
        import json

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        src_aipass = repo / "src" / "aipass"
        src_aipass.mkdir(parents=True)

        branch = src_aipass / name
        branch.mkdir()
        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = {
            "branch_info": {"branch_name": "devpulse" if is_devpulse else name},
            "identity": {"citizen_class": citizen_class},
        }
        (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")

        for shared in ["system_logs", ".ai_central"]:
            (repo / shared).mkdir()
        (src_aipass / "memory" / "memory_pool").mkdir(parents=True)
        (repo / "AIPASS_REGISTRY.json").touch()
        (src_aipass / "flow" / "flow_json").mkdir(parents=True)

        return branch

    def _make_sibling(self, branch_path, name, with_mail=True, with_dashboard=True):
        """Create a sibling branch with mail/dashboard."""
        src_aipass = branch_path.parent
        sibling = src_aipass / name
        sibling.mkdir()
        if with_mail:
            (sibling / ".ai_mail.local").mkdir()
        if with_dashboard:
            (sibling / "DASHBOARD.local.json").touch()
        return sibling

    def test_builder_includes_own_tree(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        policy = build_policy(branch)
        assert str(branch) in policy["allow_write"]

    def test_builder_includes_tmp(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        policy = build_policy(branch)
        assert tempfile.gettempdir() in policy["allow_write"]

    def test_builder_includes_shared_channels(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        repo = tmp_path / "repo"
        policy = build_policy(branch)
        assert str(repo / "system_logs") in policy["allow_write"]
        assert str(repo / ".ai_central") in policy["allow_write"]
        assert str(repo / "AIPASS_REGISTRY.json") in policy["allow_write"]

    def test_builder_excludes_git(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        repo = tmp_path / "repo"
        policy = build_policy(branch)
        assert str(repo / ".git") not in policy["allow_write"]

    def test_devpulse_includes_git(self, tmp_path):
        branch = self._make_branch(tmp_path, "devpulse", is_devpulse=True)
        repo = tmp_path / "repo"
        policy = build_policy(branch)
        assert str(repo / ".git") in policy["allow_write"]

    def test_sibling_mail_writable(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        sibling = self._make_sibling(branch, "hooks")
        policy = build_policy(branch)
        assert str(sibling / ".ai_mail.local") in policy["allow_write"]

    def test_sibling_dashboard_writable(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        sibling = self._make_sibling(branch, "hooks")
        policy = build_policy(branch)
        assert str(sibling / "DASHBOARD.local.json") in policy["allow_write"]

    def test_sibling_source_not_writable(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        sibling = self._make_sibling(branch, "hooks")
        policy = build_policy(branch)
        assert str(sibling) not in policy["allow_write"]

    def test_policy_shape(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        policy = build_policy(branch)
        assert "allow_write" in policy
        assert "deny_write" in policy
        assert "deny_read" in policy
        secret = str(tmp_path / "repo" / ".ai_central" / "broker_secret")
        assert policy["deny_write"] == [secret]
        assert policy["deny_read"] == [secret]

    def test_broker_secret_masked_for_all_roles(self, tmp_path):
        """The broker secret sits inside writable .ai_central — it must be
        deny_read AND deny_write for every role, or a sandboxed agent could
        read it and forge a devpulse identity to the broker."""
        for name in ("seedgo", "devpulse"):
            base = tmp_path / f"case_{name}"
            base.mkdir()
            branch = self._make_branch(base, name)
            repo_root = base / "repo"
            policy = build_policy(branch)
            secret = str(repo_root / ".ai_central" / "broker_secret")
            assert secret in policy["deny_read"]
            assert secret in policy["deny_write"]
            assert str(repo_root / ".ai_central") in policy["allow_write"]

    def test_claude_project_dir_included(self, tmp_path):
        branch = self._make_branch(tmp_path, "seedgo")
        encoded = str(branch.resolve()).replace("/", "-")
        claude_proj = tmp_path / ".claude" / "projects" / encoded
        claude_proj.mkdir(parents=True)

        with patch("aipass.hooks.apps.modules.sandbox.Path.home", return_value=tmp_path):
            policy = build_policy(branch)

        assert str(claude_proj) in policy["allow_write"]

    def test_no_repo_root_raises(self, tmp_path):
        bare = tmp_path / "no_repo" / "branch"
        bare.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="No .git found"):
            build_policy(bare)


class TestHandleCommand:
    """Drone routing for sandbox module."""

    def test_sandbox_no_args_calls_introspection(self):
        result = handle_command("sandbox", [])
        assert result is True

    def test_sandbox_help(self):
        result = handle_command("sandbox", ["--help"])
        assert result is True

    def test_unknown_command_returns_false(self):
        result = handle_command("other", [])
        assert result is False

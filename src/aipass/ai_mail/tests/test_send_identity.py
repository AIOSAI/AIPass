# =================== AIPass ====================
# Name: test_send_identity.py
# Description: Tests for sender identity detection chain
# Version: 1.2.0
# Created: 2026-03-10
# Modified: 2026-03-10
# =============================================

"""
Tests for Sender Identity Detection

The identity chain is ai_mail's most critical and most fragile path.
Every bug from sessions 4-7 traced back to identity detection failing.

Tests cover:
- AIPASS_CALLER_BRANCH env var (primary, set by drone)
- AIPASS_BRANCH_NAME env var (fallback, set by dispatch_monitor)
- CWD-based .trinity/passport.json walk-up
- --from flag explicit override
- Failure cases (no identity, wrong identity, cascade failures)

Audit v1 (2026-03-10): 3 agents verified all tests. Fixed 7 false positives.
Audit v2 (2026-03-10): 5 agents found 8 more issues:
- 5 tests hitting live registry instead of patched fixtures
- Contract tests matching commented-out code (substring, not line-aware)
- Contract tests missing env=spawn_env verification
- Registry fixtures using dict format when production uses list format
- No test for degenerate from_branch="@"
- No test for corrupted registry JSON
All fixed in v1.2.0.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.users.branch_detection import (
    detect_branch_from_pwd,
    find_branch_root,
    get_branch_info_from_registry,
    _lookup_branch_by_name,
)
from aipass.ai_mail.apps.handlers.email.send import resolve_sender_info
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args


# ─── Fixtures ────────────────────────────────────────────


@pytest.fixture
def temp_branch(tmp_path):
    """Create a minimal branch structure with .trinity/passport.json."""
    branch_dir = tmp_path / "src" / "aipass" / "test_branch"
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "passport.json").write_text(json.dumps({
        "branch_info": {
            "branch_name": "test_branch",
            "branch_email": "@test_branch",
        }
    }))
    return branch_dir


@pytest.fixture
def two_branches(tmp_path):
    """Create two branch structures for priority testing."""
    branches = {}
    for name in ["alpha", "beta"]:
        branch_dir = tmp_path / "src" / "aipass" / name
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(json.dumps({
            "branch_info": {"branch_name": name, "branch_email": f"@{name}"}
        }))
        branches[name] = branch_dir

    registry = {"branches": {
        "alpha": {
            "name": "ALPHA", "path": str(branches["alpha"]),
            "email": "@alpha", "status": "active", "description": "Test A",
        },
        "beta": {
            "name": "BETA", "path": str(branches["beta"]),
            "email": "@beta", "status": "active", "description": "Test B",
        },
    }}
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return branches, registry_path


@pytest.fixture
def temp_registry(tmp_path):
    """Create a temporary AIPASS_REGISTRY.json with known test branches.

    Uses dict format. Returns (registry_path, branch_data) so tests can
    assert against fixture-defined values, not live production data.
    """
    branch_data = {
        "test_branch": {
            "name": "TEST_BRANCH",
            "path": str(tmp_path / "src" / "aipass" / "test_branch"),
            "email": "@test_branch",
            "status": "active",
            "description": "Test branch for pytest",
        },
        "mock_spawn": {
            "name": "MOCK_SPAWN",
            "path": str(tmp_path / "src" / "aipass" / "mock_spawn"),
            "email": "@mock_spawn",
            "status": "active",
            "description": "Mock spawn for testing",
        },
        "spawn": {
            "name": "SPAWN",
            "path": str(tmp_path / "src" / "aipass" / "spawn"),
            "email": "@spawn",
            "status": "active",
            "description": "Mock spawn for identity testing",
        },
    }
    registry = {"branches": branch_data}
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path, branch_data


@pytest.fixture
def list_format_registry(tmp_path):
    """Create a registry using production list format (not dict).

    Production AIPASS_REGISTRY.json uses: {"branches": [{...}, {...}]}
    This fixture ensures the list format path is exercised.
    Returns (branch_dir, registry_path) for CWD-based tests.
    """
    branch_dir = tmp_path / "src" / "aipass" / "test_cwd_branch"
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "passport.json").write_text(json.dumps({
        "branch_info": {
            "branch_name": "test_cwd_branch",
            "branch_email": "@test_cwd_branch",
        }
    }))

    # List format — matches production AIPASS_REGISTRY.json
    registry = {"branches": [
        {
            "name": "TEST_CWD_BRANCH",
            "path": str(branch_dir),
            "email": "@test_cwd_branch",
            "status": "active",
            "description": "CWD detection test branch",
        },
        {
            "name": "SPAWN",
            "path": str(tmp_path / "src" / "aipass" / "spawn"),
            "email": "@spawn",
            "status": "active",
            "description": "Mock spawn for identity testing",
        },
    ]}
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return branch_dir, registry_path


@pytest.fixture
def clean_env():
    """Strip all AIPASS identity env vars for a clean test state."""
    env_keys = [
        "AIPASS_CALLER_BRANCH",
        "AIPASS_CALLER_CWD",
        "AIPASS_BRANCH_NAME",
    ]
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    yield
    # Restore
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ─── detect_branch_from_pwd() tests ─────────────────────


class TestDetectBranchFromPwd:
    """Tests for the primary identity detection function."""

    def test_detects_from_caller_branch_env(self, clean_env, temp_registry):
        """AIPASS_CALLER_BRANCH env var should be the primary detection method."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "spawn"
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["name"] == "SPAWN"
            assert result["email"] == "@spawn"

    def test_detects_from_caller_branch_case_insensitive(self, clean_env, temp_registry):
        """Branch name lookup should be case-insensitive."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "SPAWN"
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["email"] == "@spawn"

    def test_caller_branch_takes_priority_over_cwd(self, clean_env, two_branches):
        """AIPASS_CALLER_BRANCH should win even if CWD resolves to a different branch."""
        branches, registry_path = two_branches
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            # Point CWD to alpha, but env says beta
            os.environ["AIPASS_CALLER_BRANCH"] = "beta"
            os.environ["AIPASS_CALLER_CWD"] = str(branches["alpha"])
            result = detect_branch_from_pwd()
            assert result is not None
            # Must be beta (env), NOT alpha (CWD)
            assert result["name"] == "BETA"
            assert result["email"] == "@beta"

    def test_falls_back_to_caller_cwd(self, clean_env, list_format_registry):
        """When AIPASS_CALLER_BRANCH is absent, use AIPASS_CALLER_CWD path."""
        branch_dir, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["email"] == "@test_cwd_branch"

    def test_returns_none_with_no_env_and_bad_cwd(self, clean_env, tmp_path):
        """No env vars + CWD outside any branch = None."""
        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
        result = detect_branch_from_pwd()
        assert result is None

    def test_invalid_branch_name_falls_through(self, clean_env, tmp_path, temp_registry):
        """Nonexistent branch in AIPASS_CALLER_BRANCH should fall through to CWD.

        When env branch name is not in registry, function falls back to
        AIPASS_CALLER_CWD. If that also fails, result is None.
        """
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "totally_fake_branch_xyz"
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)  # Also not a branch
            result = detect_branch_from_pwd()
            assert result is None


# ─── find_branch_root() tests ───────────────────────────


class TestFindBranchRoot:
    """Tests for the .trinity/passport.json walk-up."""

    def test_finds_root_at_exact_dir(self, temp_branch):
        """Should find branch root when starting exactly at it."""
        result = find_branch_root(temp_branch)
        assert result == temp_branch

    def test_finds_root_from_subdirectory(self, temp_branch):
        """Should find branch root when starting from a subdirectory."""
        subdir = temp_branch / "apps" / "handlers"
        subdir.mkdir(parents=True)
        result = find_branch_root(subdir)
        assert result == temp_branch

    def test_finds_root_from_deep_nesting(self, temp_branch):
        """Should find branch root even from deeply nested dirs."""
        deep = temp_branch / "apps" / "handlers" / "email" / "nested"
        deep.mkdir(parents=True)
        result = find_branch_root(deep)
        assert result == temp_branch

    def test_returns_none_outside_branch(self, tmp_path):
        """Should return None when no .trinity/passport.json exists above."""
        result = find_branch_root(tmp_path)
        assert result is None

    def test_returns_none_at_filesystem_root(self):
        """Should return None (not infinite loop) when starting at fs root."""
        result = find_branch_root(Path(Path(__file__).resolve().anchor))
        assert result is None

    def test_doesnt_cross_branch_boundaries(self, tmp_path):
        """Two branches side-by-side: should find correct root for each."""
        branch_a = tmp_path / "branch_a"
        branch_b = tmp_path / "branch_b"
        for b in [branch_a, branch_b]:
            trinity = b / ".trinity"
            trinity.mkdir(parents=True)
            (trinity / "passport.json").write_text("{}")

        assert find_branch_root(branch_a) == branch_a
        assert find_branch_root(branch_b) == branch_b
        # Subdir of A should find A, not B
        sub_a = branch_a / "apps"
        sub_a.mkdir()
        assert find_branch_root(sub_a) == branch_a


# ─── _lookup_branch_by_name() tests (isolated with temp registry) ──


class TestLookupBranchByName:
    """Tests for registry name lookup. Uses patched temp registry."""

    def test_finds_existing_branch(self, temp_registry):
        """Should find a branch that exists in the registry."""
        registry_path, branch_data = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _lookup_branch_by_name("mock_spawn")
            assert result is not None
            assert result["email"] == "@mock_spawn"
            assert result["name"] == "MOCK_SPAWN"

    def test_case_insensitive_lookup(self, temp_registry):
        """Should match regardless of case."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            lower = _lookup_branch_by_name("test_branch")
            upper = _lookup_branch_by_name("TEST_BRANCH")
            assert lower is not None
            assert upper is not None
            assert lower["email"] == upper["email"] == "@test_branch"

    def test_returns_none_for_nonexistent(self, temp_registry):
        """Should return None for a branch not in registry."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _lookup_branch_by_name("this_branch_does_not_exist_xyz")
            assert result is None

    def test_returns_none_when_registry_missing(self, tmp_path):
        """Should return None (not crash) when registry file doesn't exist."""
        fake_path = tmp_path / "nonexistent_registry.json"
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", fake_path):
            result = _lookup_branch_by_name("anything")
            assert result is None

    def test_returns_none_when_registry_corrupted(self, tmp_path):
        """Should return None (not crash) when registry JSON is malformed."""
        corrupt_path = tmp_path / "AIPASS_REGISTRY.json"
        corrupt_path.write_text("{this is not valid json!!!")
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", corrupt_path):
            result = _lookup_branch_by_name("anything")
            assert result is None

    def test_list_format_registry_works(self, list_format_registry):
        """Should work with production list-format registry (not just dict)."""
        _, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _lookup_branch_by_name("spawn")
            assert result is not None
            assert result["name"] == "SPAWN"
            assert result["email"] == "@spawn"


# ─── get_branch_info_from_registry() tests ───────────────


class TestGetBranchInfoFromRegistry:
    """Tests for path-based registry lookup. Uses patched temp registry."""

    def test_finds_branch_by_absolute_path(self, temp_registry, temp_branch):
        """Should find branch when given its absolute path."""
        registry_path, branch_data = temp_registry
        # Patch both the registry path AND update the registry entry to use temp_branch's actual path
        branch_data["test_branch"]["path"] = str(temp_branch)
        registry_path.write_text(json.dumps({"branches": branch_data}, indent=2))
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_branch_info_from_registry(temp_branch)
            assert result is not None
            assert result["email"] == "@test_branch"
            assert result["name"] == "TEST_BRANCH"

    def test_returns_none_for_random_path(self, temp_registry, tmp_path):
        """Should return None for a path not in registry."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = get_branch_info_from_registry(tmp_path / "random" / "path")
            assert result is None


# ─── parse_send_args() --from flag tests ─────────────────


class TestSendArgsFromFlag:
    """Tests for the --from explicit sender override."""

    def test_from_flag_parsed(self):
        """--from @spawn should be extracted."""
        result = parse_send_args(["@ai_mail", "Subject", "Body", "--from", "@spawn"])
        assert result["from_branch"] == "@spawn"
        assert result["mode"] == "direct"
        assert result["recipients"] == ["@ai_mail"]

    def test_from_flag_with_dispatch(self):
        """--from and --dispatch should both work together."""
        result = parse_send_args([
            "@ai_mail", "Subject", "Body", "--from", "@backup", "--dispatch"
        ])
        assert result["from_branch"] == "@backup"
        assert result["auto_execute"] is True

    def test_from_flag_missing_value(self):
        """--from without a value should error."""
        result = parse_send_args(["@ai_mail", "Subject", "Body", "--from"])
        assert result["mode"] == "error"

    def test_no_from_flag_is_none(self):
        """Without --from, from_branch should be None."""
        result = parse_send_args(["@spawn", "Subject", "Body"])
        assert result["from_branch"] is None


# ─── resolve_sender_info() tests ─────────────────────────


class TestResolveSenderInfo:
    """Tests for the sender resolution function in send.py."""

    def test_explicit_from_branch_resolves(self, tmp_path):
        """Explicit from_branch should use registry lookup, not CWD."""
        def mock_get_branch_by_email(email):
            if email == "@spawn":
                return {
                    "name": "SPAWN",
                    "path": "src/aipass/spawn",
                    "email": "@spawn",
                }
            return None

        result = resolve_sender_info(
            from_branch="@spawn",
            repo_root=tmp_path,
            ai_mail_dir=tmp_path / "ai_mail",
            get_branch_by_email_fn=mock_get_branch_by_email,
            get_current_user_fn=lambda: {"email_address": "@ai_mail"},
        )
        assert result["email_address"] == "@spawn"
        assert result["display_name"] == "SPAWN"
        # Verify path resolution (relative path resolved against repo_root)
        assert "mailbox_path" in result
        assert str(tmp_path) in result["mailbox_path"]

    def test_no_from_branch_uses_current_user(self, tmp_path):
        """Without from_branch, should delegate to get_current_user_fn."""
        fallback_user = {
            "email_address": "@trigger",
            "display_name": "TRIGGER",
            "mailbox_path": str(tmp_path / "mailbox"),
        }
        result = resolve_sender_info(
            from_branch=None,
            repo_root=tmp_path,
            ai_mail_dir=tmp_path / "ai_mail",
            get_branch_by_email_fn=lambda e: None,
            get_current_user_fn=lambda: fallback_user,
        )
        assert result["email_address"] == "@trigger"

    def test_from_branch_not_in_registry_still_works(self, tmp_path):
        """Unknown from_branch should still construct valid sender info."""
        result = resolve_sender_info(
            from_branch="@mystery",
            repo_root=tmp_path,
            ai_mail_dir=tmp_path / "ai_mail",
            get_branch_by_email_fn=lambda e: None,  # Not found
            get_current_user_fn=lambda: {"email_address": "@ai_mail"},
        )
        # Should still resolve, just with constructed info
        assert result["email_address"] == "@mystery"
        assert result["display_name"] == "MYSTERY"

    def test_from_branch_at_only_is_degenerate(self, tmp_path):
        """from_branch="@" (just @ symbol) should produce degenerate but not crash.

        This is an edge case: lstrip('@') produces empty string.
        The system should handle it without crashing.
        """
        result = resolve_sender_info(
            from_branch="@",
            repo_root=tmp_path,
            ai_mail_dir=tmp_path / "ai_mail",
            get_branch_by_email_fn=lambda e: None,
            get_current_user_fn=lambda: {"email_address": "@ai_mail"},
        )
        # Should not crash — verify degenerate but predictable output
        assert result is not None
        assert result["email_address"] == "@"
        assert result["display_name"] == ""
        assert "mailbox_path" in result


# ─── Dispatch env var tests ──────────────────────────────


class TestDispatchEnvIsolation:
    """Tests for the dispatch_monitor env var contract.

    dispatch_monitor.py must:
    1. Strip AIPASS_CALLER_BRANCH (prevents parent context leak)
    2. Strip AIPASS_CALLER_CWD (prevents stale CWD)
    3. Set AIPASS_BRANCH_NAME (CWD-independent identity)
    4. Pass spawn_env to subprocess.run (actually use the isolated env)

    Contract tests read source code and verify critical lines exist.
    Lines are filtered to exclude comments — commented-out code won't match.
    """

    @staticmethod
    def _load_active_source():
        """Load dispatch_monitor.py source with comment lines filtered out."""
        monitor_path = (
            Path(__file__).resolve().parents[1]
            / "apps" / "handlers" / "dispatch" / "dispatch_monitor.py"
        )
        source = monitor_path.read_text()
        active_lines = [
            line for line in source.splitlines()
            if not line.strip().startswith('#')
        ]
        return '\n'.join(active_lines)

    def test_dispatch_monitor_sets_branch_name_in_env(self):
        """dispatch_monitor.py must set AIPASS_BRANCH_NAME from branch_email.

        Checks the full assignment line (not split across assertions).
        Comment lines are filtered out — a commented-out line won't pass.
        """
        active_source = self._load_active_source()
        assert 'spawn_env["AIPASS_BRANCH_NAME"] = branch_email.lstrip("@")' in active_source, \
            "dispatch_monitor.py must set AIPASS_BRANCH_NAME = branch_email.lstrip('@') in spawn_env"

    def test_dispatch_monitor_strips_caller_vars(self):
        """dispatch_monitor.py must strip AIPASS_CALLER_BRANCH and AIPASS_CALLER_CWD.

        Contract test — verifies the env isolation lines exist in source.
        Checks full pop() calls including the None default.
        """
        active_source = self._load_active_source()
        assert 'spawn_env.pop("AIPASS_CALLER_BRANCH", None)' in active_source, \
            "dispatch_monitor.py must strip AIPASS_CALLER_BRANCH from spawn_env"
        assert 'spawn_env.pop("AIPASS_CALLER_CWD", None)' in active_source, \
            "dispatch_monitor.py must strip AIPASS_CALLER_CWD from spawn_env"

    def test_dispatch_monitor_passes_spawn_env_to_subprocess(self):
        """dispatch_monitor.py must pass env=spawn_env to subprocess.run.

        Without this, all env var isolation is useless — the subprocess
        would inherit os.environ instead of the cleaned spawn_env.
        """
        active_source = self._load_active_source()
        assert 'env=spawn_env' in active_source, \
            "dispatch_monitor.py must pass env=spawn_env to subprocess.run"

    def test_detect_resolves_identity_when_cwd_is_wrong(self, clean_env, tmp_path, list_format_registry):
        """When AIPASS_CALLER_BRANCH is set but CWD is outside any branch,
        detection should succeed via the env var path, not CWD.

        This is the dispatch scenario: agent cd'd away, CWD is useless,
        but AIPASS_CALLER_BRANCH (set by drone from AIPASS_BRANCH_NAME) works.
        """
        _, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "spawn"
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)  # Points nowhere useful
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["name"] == "SPAWN"
            assert result["email"] == "@spawn"


# ─── Anti-regression tests ───────────────────────────────


class TestAntiRegression:
    """Tests for specific bugs we've fixed. These must NEVER break again."""

    def test_no_silent_ai_mail_identity_from_cwd(self, clean_env, tmp_path, temp_registry):
        """BUG (session 5): Path.cwd() inside ai_mail subprocess detected @ai_mail as sender.

        When no env vars are set and AIPASS_CALLER_CWD points outside any branch,
        detect_branch_from_pwd must return None — never silently detect ai_mail.
        """
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
            result = detect_branch_from_pwd()
            assert result is None, \
                "With CWD outside any branch, detection must return None, not silently detect a branch"

    def test_invalid_caller_cwd_doesnt_crash(self, clean_env, tmp_path, temp_registry):
        """Stale or nonexistent AIPASS_CALLER_CWD should return None, not crash."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_CWD"] = "/nonexistent/path/that/doesnt/exist"
            result = detect_branch_from_pwd()
            assert result is None

    def test_empty_caller_branch_falls_through_to_cwd(self, clean_env, list_format_registry):
        """Empty string in AIPASS_CALLER_BRANCH should fall through to CWD detection.

        Verifies the empty-string is treated as falsy and CWD path is used instead.
        """
        branch_dir, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = ""
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
            result = detect_branch_from_pwd()
            assert result is not None, "Empty AIPASS_CALLER_BRANCH should fall through to CWD"
            assert result["email"] == "@test_cwd_branch", \
                "CWD points to test_cwd_branch, so after fallthrough, it should be detected"

    def test_send_args_all_flags_combined(self):
        """All flags together should parse without interference."""
        result = parse_send_args([
            "@spawn", "Subject", "Body",
            "--from", "@backup",
            "--dispatch",
            "--no-memory-save",
            "--reply-to", "@flow",
        ])
        assert result["from_branch"] == "@backup"
        assert result["auto_execute"] is True
        assert result["no_memory_save"] is True
        assert result["reply_to"] == "@flow"
        assert result["recipients"] == ["@spawn"]
        assert result["mode"] == "direct"

# =================== AIPass ====================
# Name: test_send_identity.py
# Description: Tests for sender identity detection chain
# Version: 1.2.2
# Created: 2026-03-10
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/users/branch_detection.py and the sender identity chain in apps/handlers/email/send.py."""

# The identity chain is ai_mail's most critical and most fragile path.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — os.environ.setdefault on the win32 import-time branch, unreachable on POSIX

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.email.contacts import register_contact
from aipass.ai_mail.apps.handlers.users.branch_detection import (
    detect_branch_from_pwd,
    find_branch_root,
    get_branch_info_from_registry,
)
from aipass.ai_mail.apps.handlers.email.send import resolve_sender_info
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args


@pytest.fixture
def temp_branch(tmp_path):
    """Create a minimal branch structure with .trinity/passport.json."""
    branch_dir = tmp_path / "src" / "aipass" / "test_branch"
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {
                    "branch_name": "test_branch",
                    "branch_email": "@test_branch",
                }
            }
        ),
        encoding="utf-8",
    )
    return branch_dir


@pytest.fixture
def two_branches(tmp_path):
    """Create two branch structures for priority testing."""
    branches = {}
    for name in ["alpha", "beta"]:
        branch_dir = tmp_path / "src" / "aipass" / name
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": name, "branch_email": f"@{name}"}}),
            encoding="utf-8",
        )
        branches[name] = branch_dir

    registry = {
        "branches": {
            "alpha": {
                "name": "ALPHA",
                "path": str(branches["alpha"]),
                "email": "@alpha",
                "status": "active",
                "description": "Test A",
            },
            "beta": {
                "name": "BETA",
                "path": str(branches["beta"]),
                "email": "@beta",
                "status": "active",
                "description": "Test B",
            },
        }
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return branches, registry_path


@pytest.fixture
def temp_registry(tmp_path):
    """Create a temporary AIPASS_REGISTRY.json with known test branches."""
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
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_path, branch_data


@pytest.fixture
def list_format_registry(tmp_path):
    """Create a registry using production list format (not dict)."""
    branch_dir = tmp_path / "src" / "aipass" / "test_cwd_branch"
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {
                    "branch_name": "test_cwd_branch",
                    "branch_email": "@test_cwd_branch",
                }
            }
        ),
        encoding="utf-8",
    )

    registry = {
        "branches": [
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
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return branch_dir, registry_path


@pytest.fixture
def clean_env():
    """Strip all AIPASS identity env vars for a clean test state."""
    env_keys = [
        "AIPASS_CALLER_BRANCH",
        "AIPASS_CALLER_CWD",
        "AIPASS_BRANCH_NAME",
        # A credential: an ambient "passport"/"assigned" lets the fence accept a caller
        # outside any branch, disabling what these tests assert. Also stripped in conftest.
        "AIPASS_CALLER_IDENTITY_SOURCE",
    ]
    saved = {k: os.environ.pop(k, None) for k in env_keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


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
            os.environ["AIPASS_CALLER_BRANCH"] = "beta"
            os.environ["AIPASS_CALLER_CWD"] = str(branches["alpha"])
            result = detect_branch_from_pwd()
            assert result is not None
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

    def test_unknown_branch_synthesizes_from_env(self, clean_env, tmp_path, temp_registry):
        """Unknown branch in AIPASS_CALLER_BRANCH synthesizes info from env vars."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            # Synthesis serves callers in their OWN branch (a passport) that this registry
            # does not know, never callers standing nowhere: the fence refuses those.
            (tmp_path / ".trinity").mkdir(parents=True, exist_ok=True)
            (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
            os.environ["AIPASS_CALLER_BRANCH"] = "VERA-STUDIO"
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["name"].lower() == "vera-studio"
            assert result["email"].lower() == "@vera-studio"


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
            (trinity / "passport.json").write_text("{}", encoding="utf-8")

        assert find_branch_root(branch_a) == branch_a
        assert find_branch_root(branch_b) == branch_b
        sub_a = branch_a / "apps"
        sub_a.mkdir()
        assert find_branch_root(sub_a) == branch_a


def _registry_answer(name: str):
    """The registry row detect_branch_from_pwd seats a caller named only by AIPASS_CALLER_BRANCH.

    No caller cwd, so nothing is synthesized; the address book is recorded and answers
    nothing, so a found row can only have come from the registry.
    """
    asked: list[str] = []
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIPASS_CALLER_")}
    env["AIPASS_CALLER_BRANCH"] = name
    with (
        patch.dict(os.environ, env, clear=True),
        patch("aipass.ai_mail.apps.handlers.email.contacts.get_contact", side_effect=asked.append),
    ):
        found = detect_branch_from_pwd()
    # The address book is asked exactly when the registry had no row.
    assert asked == ([] if found else [name])
    return found


class TestLookupBranchByName:
    """Tests for registry name lookup. Uses patched temp registry."""

    def test_finds_existing_branch(self, temp_registry):
        """Should find a branch that exists in the registry."""
        registry_path, branch_data = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _registry_answer("mock_spawn")
            assert result is not None
            assert result["email"] == "@mock_spawn"
            assert result["name"] == "MOCK_SPAWN"

    def test_case_insensitive_lookup(self, temp_registry):
        """Should match regardless of case."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            lower = _registry_answer("test_branch")
            upper = _registry_answer("TEST_BRANCH")
            assert lower is not None
            assert upper is not None
            assert lower["email"] == upper["email"] == "@test_branch"

    def test_returns_none_for_nonexistent(self, temp_registry):
        """Should return None for a branch not in registry."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _registry_answer("this_branch_does_not_exist_xyz")
            assert result is None

    def test_returns_none_when_registry_missing(self, tmp_path):
        """Should return None (not crash) when registry file doesn't exist."""
        fake_path = tmp_path / "nonexistent_registry.json"
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", fake_path):
            result = _registry_answer("anything")
            assert result is None

    def test_returns_none_when_registry_corrupted(self, tmp_path):
        """Should return None (not crash) when registry JSON is malformed."""
        corrupt_path = tmp_path / "AIPASS_REGISTRY.json"
        corrupt_path.write_text("{this is not valid json!!!", encoding="utf-8")
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", corrupt_path):
            result = _registry_answer("anything")
            assert result is None

    def test_list_format_registry_works(self, list_format_registry):
        """Should work with production list-format registry (not just dict)."""
        _, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            result = _registry_answer("spawn")
            assert result is not None
            assert result["name"] == "SPAWN"
            assert result["email"] == "@spawn"


class TestGetBranchInfoFromRegistry:
    """Tests for path-based registry lookup. Uses patched temp registry."""

    def test_finds_branch_by_absolute_path(self, temp_registry, temp_branch):
        """Should find branch when given its absolute path."""
        registry_path, branch_data = temp_registry
        branch_data["test_branch"]["path"] = str(temp_branch)
        registry_path.write_text(json.dumps({"branches": branch_data}, indent=2), encoding="utf-8")
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
        result = parse_send_args(["@ai_mail", "Subject", "Body", "--from", "@backup", "--dispatch"])
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
        assert result["email_address"] == "@mystery"
        assert result["display_name"] == "MYSTERY"

    def test_from_branch_at_only_is_degenerate(self, tmp_path):
        """from_branch="@" (just @ symbol) should produce degenerate but not crash."""
        result = resolve_sender_info(
            from_branch="@",
            repo_root=tmp_path,
            ai_mail_dir=tmp_path / "ai_mail",
            get_branch_by_email_fn=lambda e: None,
            get_current_user_fn=lambda: {"email_address": "@ai_mail"},
        )
        assert result is not None
        assert result["email_address"] == "@"
        assert result["display_name"] == ""
        assert "mailbox_path" in result


class TestDispatchEnvIsolation:
    """Tests for the dispatch_monitor env var contract.

    Strip AIPASS_CALLER_BRANCH/CWD, set AIPASS_BRANCH_NAME, pass spawn_env to the
    subprocess. Read from source with comment lines filtered out.
    """

    @staticmethod
    def _load_active_source():
        """Load dispatch_monitor.py source with comment lines filtered out."""
        monitor_path = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "dispatch" / "dispatch_monitor.py"
        source = monitor_path.read_text(encoding="utf-8")
        active_lines = [line for line in source.splitlines() if not line.strip().startswith("#")]
        return "\n".join(active_lines)

    def test_dispatch_monitor_sets_branch_name_in_env(self):
        """dispatch_monitor.py must set AIPASS_BRANCH_NAME from branch_email."""
        active_source = self._load_active_source()
        assert 'spawn_env["AIPASS_BRANCH_NAME"] = branch_email.lstrip("@")' in active_source, (
            "dispatch_monitor.py must set AIPASS_BRANCH_NAME = branch_email.lstrip('@') in spawn_env"
        )

    def test_dispatch_monitor_strips_caller_vars(self):
        """dispatch_monitor.py must strip AIPASS_CALLER_BRANCH and AIPASS_CALLER_CWD."""
        active_source = self._load_active_source()
        assert 'spawn_env.pop("AIPASS_CALLER_BRANCH", None)' in active_source, (
            "dispatch_monitor.py must strip AIPASS_CALLER_BRANCH from spawn_env"
        )
        assert 'spawn_env.pop("AIPASS_CALLER_CWD", None)' in active_source, (
            "dispatch_monitor.py must strip AIPASS_CALLER_CWD from spawn_env"
        )

    def test_dispatch_monitor_passes_spawn_env_to_subprocess(self):
        """dispatch_monitor.py must pass spawn_env as the subprocess env.

        Only the popen_kwargs dict form is live; accepting the dead env=spawn_env
        spelling too would let the dict form drop without a red.
        """
        active_source = self._load_active_source()
        assert '"env": spawn_env' in active_source, "dispatch_monitor.py must pass spawn_env as the subprocess env"

    def test_detect_refuses_when_cwd_is_outside_any_branch(self, clean_env, tmp_path, list_format_registry):
        """A CALLER_BRANCH claim no longer survives a CALLER_CWD outside any branch.

        At the repo root drone stamps CALLER_BRANCH from the project directory name,
        which collides with the citizen of that name; a refusal is recoverable, the wrong sender is not.
        """
        _, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "spawn"
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)  # Points nowhere useful
            assert detect_branch_from_pwd() is None

    def test_assigned_identity_still_beats_location_inside_a_branch(self, clean_env, list_format_registry):
        """The protection survives the fence: standing in SOMEONE ELSE'S branch,
        the caller is still whoever drone stamped, not whoever lives there.

        The fence asks "is the caller in A branch", never "THEIR branch": an agent that
        cds into another branch to read its code is still itself.
        """
        branch_dir, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = "spawn"
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)  # test_cwd_branch's home
            result = detect_branch_from_pwd()
            assert result is not None
            assert result["email"] == "@spawn"


class TestAntiRegression:
    """Tests for specific bugs we've fixed. These must NEVER break again."""

    def test_no_silent_ai_mail_identity_from_cwd(self, clean_env, tmp_path, temp_registry):
        """BUG: Path.cwd() inside ai_mail subprocess detected @ai_mail as sender."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
            result = detect_branch_from_pwd()
            assert result is None, (
                "With CWD outside any branch, detection must return None, not silently detect a branch"
            )

    def test_invalid_caller_cwd_doesnt_crash(self, clean_env, tmp_path, temp_registry):
        """Stale or nonexistent AIPASS_CALLER_CWD should return None, not crash."""
        registry_path, _ = temp_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_CWD"] = "/nonexistent/path/that/doesnt/exist"
            result = detect_branch_from_pwd()
            assert result is None

    def test_empty_caller_branch_falls_through_to_cwd(self, clean_env, list_format_registry):
        """Empty string in AIPASS_CALLER_BRANCH should fall through to CWD detection."""
        branch_dir, registry_path = list_format_registry
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path):
            os.environ["AIPASS_CALLER_BRANCH"] = ""
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
            result = detect_branch_from_pwd()
            assert result is not None, "Empty AIPASS_CALLER_BRANCH should fall through to CWD"
            assert result["email"] == "@test_cwd_branch", (
                "CWD points to test_cwd_branch, so after fallthrough, it should be detected"
            )

    def test_send_args_all_flags_combined(self):
        """All flags together should parse without interference."""
        result = parse_send_args(
            [
                "@spawn",
                "Subject",
                "Body",
                "--from",
                "@backup",
                "--dispatch",
                "--no-memory-save",
                "--reply-to",
                "@flow",
            ]
        )
        assert result["from_branch"] == "@backup"
        assert result["auto_execute"] is True
        assert result["no_memory_save"] is True
        assert result["reply_to"] == "@flow"
        assert result["recipients"] == ["@spawn"]
        assert result["mode"] == "direct"


def _seat_registry(registry: Path, seat: Path) -> Path:
    """Write *registry* holding one row for *seat*, named after the file: the name tells which registry answered."""
    name = registry.name.removesuffix("_REGISTRY.json")
    registry.write_text(json.dumps({"branches": [{"name": name, "path": str(seat)}]}), encoding="utf-8")
    return registry


def _answering_registry(seat: Path, aipass_registry: Path):
    """The name of the registry that answers a lookup of *seat* by path, or None when none does."""
    with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", aipass_registry):
        info = get_branch_info_from_registry(seat)
    return None if info is None else info["name"]


class TestFindCallerRegistry:
    """The caller registry fallback for external project branches, read through the public path lookup."""

    def test_returns_none_when_no_env(self, clean_env, tmp_path, monkeypatch):
        """No AIPASS_CALLER_CWD: a registry holding the seat is never consulted, not even in the process CWD."""
        seat = tmp_path / "seat"
        _seat_registry(tmp_path / "VERA_REGISTRY.json", seat)
        monkeypatch.chdir(tmp_path)

        assert _answering_registry(seat, tmp_path / "other" / "AIPASS_REGISTRY.json") is None

    def test_returns_none_when_no_registry_in_tree(self, clean_env, tmp_path):
        """No *_REGISTRY.json under AIPASS_CALLER_CWD: the lookup answers None."""
        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)

        assert _answering_registry(tmp_path / "seat", tmp_path / "other" / "AIPASS_REGISTRY.json") is None

    def test_finds_registry_in_cwd(self, clean_env, tmp_path):
        """A registry in the caller CWD answers."""
        seat = tmp_path / "seat"
        _seat_registry(tmp_path / "AIPASS_REGISTRY.json", seat)

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)

        assert _answering_registry(seat, tmp_path / "other" / "AIPASS_REGISTRY.json") == "AIPASS"

    def test_finds_registry_in_parent(self, clean_env, tmp_path):
        """A registry in a parent directory of the caller CWD answers."""
        seat = tmp_path / "seat"
        _seat_registry(tmp_path / "AIPASS_REGISTRY.json", seat)
        nested = tmp_path / "src" / "vera"
        nested.mkdir(parents=True)

        os.environ["AIPASS_CALLER_CWD"] = str(nested)

        assert _answering_registry(seat, tmp_path / "other" / "AIPASS_REGISTRY.json") == "AIPASS"

    def test_skips_aipass_registry_itself(self, clean_env, tmp_path):
        """The AIPass registry found again as the caller's answers nothing a second time.

        Not visible alone (a second read of the same empty registry also answers None);
        test_prefers_external_registry_over_aipass_one is where the skip decides the answer.
        """
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text('{"branches": []}', encoding="utf-8")

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)

        assert _answering_registry(tmp_path / "seat", registry) is None

    # External projects name their registry PROJECTNAME_REGISTRY.json; a fallback
    # matching only AIPASS_REGISTRY.json never fires for the callers it exists to serve.

    def test_finds_external_project_registry(self, clean_env, tmp_path):
        """A PROJECTNAME_REGISTRY.json answers, not just AIPASS_REGISTRY.json."""
        seat = tmp_path / "seat"
        _seat_registry(tmp_path / "VERA-STUDIO_REGISTRY.json", seat)
        nested = tmp_path / "src" / "vera_studio" / "vera"
        nested.mkdir(parents=True)

        os.environ["AIPASS_CALLER_CWD"] = str(nested)

        assert _answering_registry(seat, tmp_path / "other" / "AIPASS_REGISTRY.json") == "VERA-STUDIO"

    def test_prefers_external_registry_over_aipass_one(self, clean_env, tmp_path):
        """The double-lookup guard skips the AIPass registry when both sit together, so the external one answers."""
        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text('{"branches": []}', encoding="utf-8")
        seat = tmp_path / "seat"
        _seat_registry(tmp_path / "VERA-STUDIO_REGISTRY.json", seat)

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)

        assert _answering_registry(seat, aipass_registry) == "VERA-STUDIO"

    def test_multiple_registries_resolve_deterministically(self, clean_env, tmp_path):
        """sorted() so a dir holding several registries always yields the same one."""
        seat = tmp_path / "seat"
        for name in ("ZEBRA_REGISTRY.json", "ALPHA_REGISTRY.json", "MIDDLE_REGISTRY.json"):
            _seat_registry(tmp_path / name, seat)

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
        other = tmp_path / "other" / "AIPASS_REGISTRY.json"

        assert [_answering_registry(seat, other) for _ in range(3)] == ["ALPHA"] * 3

    def test_unrelated_json_is_not_treated_as_a_registry(self, clean_env, tmp_path):
        """The glob is *_REGISTRY.json — arbitrary JSON in the tree is ignored, even when it holds the seat."""
        seat = tmp_path / "seat"
        row = json.dumps({"branches": [{"name": "UNRELATED", "path": str(seat)}]})
        (tmp_path / "package.json").write_text(row, encoding="utf-8")
        (tmp_path / "REGISTRY.json").write_text(row, encoding="utf-8")

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)

        assert _answering_registry(seat, tmp_path / "other" / "AIPASS_REGISTRY.json") is None

    def test_external_branch_resolves_by_relative_path(self, clean_env, tmp_path):
        """End of the sender-detection chain: relative path resolves against the registry dir."""
        branch_dir = tmp_path / "src" / "vera_studio" / "vera"
        branch_dir.mkdir(parents=True)
        registry = tmp_path / "VERA-STUDIO_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "VERA", "path": "src/vera_studio/vera", "email": "@vera"}]}),
            encoding="utf-8",
        )

        os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
        with patch(
            "aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH",
            tmp_path / "other" / "AIPASS_REGISTRY.json",
        ):
            info = get_branch_info_from_registry(branch_dir)

        assert info is not None
        assert info["email"] == "@vera"


def _caller_seated(monkeypatch, name: str, caller_cwd: Path):
    """The row detect_branch_from_pwd seats for a caller named *name* standing in *caller_cwd*.

    The source is "assigned", so a cwd outside any branch is not refused; the address
    book answers nothing, so a row with an email came from a registry.
    """
    asked: list[str] = []
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", name)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller_cwd))
    monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
    with patch("aipass.ai_mail.apps.handlers.email.contacts.get_contact", side_effect=asked.append):
        found = detect_branch_from_pwd()
    assert found is not None
    # The address book is asked exactly when no registry had the row.
    assert asked == ([] if found.get("email") else [name])
    return found


class TestCallerRegistryFallback:
    """Tests for branch lookup fallback to external project registry."""

    def test_lookup_by_name_falls_back_to_caller_registry(self, clean_env, tmp_path, monkeypatch):
        """The name lookup finds an external branch via the caller registry."""
        caller_registry = tmp_path / "AIPASS_REGISTRY.json"
        caller_registry.write_text(
            json.dumps(
                {"branches": [{"name": "VERA", "path": str(tmp_path / "vera"), "email": "@vera", "status": "active"}]}
            ),
            encoding="utf-8",
        )

        empty_aipass = tmp_path / "other" / "AIPASS_REGISTRY.json"
        empty_aipass.parent.mkdir(parents=True)
        empty_aipass.write_text('{"branches": []}', encoding="utf-8")

        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", empty_aipass):
            result = _caller_seated(monkeypatch, "vera", tmp_path)

        assert result["email"] == "@vera"
        assert result["name"] == "VERA"

    def test_lookup_by_name_prefers_aipass_registry(self, clean_env, tmp_path, monkeypatch):
        """The name lookup returns the AIPass row first when the branch exists in both."""
        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(
            json.dumps(
                {
                    "branches": [
                        {"name": "SPAWN", "path": str(tmp_path / "spawn"), "email": "@spawn-aipass", "status": "active"}
                    ]
                }
            ),
            encoding="utf-8",
        )

        caller_dir = tmp_path / "external"
        caller_dir.mkdir()
        caller_registry = caller_dir / "AIPASS_REGISTRY.json"
        caller_registry.write_text(
            json.dumps(
                {
                    "branches": [
                        {
                            "name": "SPAWN",
                            "path": str(tmp_path / "other_spawn"),
                            "email": "@spawn-external",
                            "status": "active",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", aipass_registry):
            result = _caller_seated(monkeypatch, "spawn", caller_dir)

        assert result["email"] == "@spawn-aipass"

    def test_get_branch_info_falls_back_to_caller_registry(self, clean_env, tmp_path):
        """get_branch_info_from_registry finds external branch path via caller registry."""
        vera_dir = tmp_path / "vera_studio" / "src" / "vera"
        vera_dir.mkdir(parents=True)

        caller_registry = tmp_path / "vera_studio" / "AIPASS_REGISTRY.json"
        caller_registry.write_text(
            json.dumps({"branches": [{"name": "VERA", "path": str(vera_dir), "email": "@vera", "status": "active"}]}),
            encoding="utf-8",
        )

        empty_aipass = tmp_path / "AIPASS_REGISTRY.json"
        empty_aipass.write_text('{"branches": []}', encoding="utf-8")

        os.environ["AIPASS_CALLER_CWD"] = str(tmp_path / "vera_studio" / "src" / "vera")
        with patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", empty_aipass):
            result = get_branch_info_from_registry(vera_dir)

        assert result is not None
        assert result["email"] == "@vera"


class TestGetContactInfo:
    """A contact row surviving after its branch directory is gone must not
    be handed back as "verified" identity: a dead fixture row would serve its mailbox.
    """

    @staticmethod
    def _caller_named(monkeypatch, tmp_path, name):
        """Who detect_branch_from_pwd says the caller is when only AIPASS_CALLER_BRANCH names it.

        The registry is an empty tmp path, so the address book is the only lane
        that can answer; with no caller cwd nothing is synthesized.
        """
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH",
            tmp_path / "AIPASS_REGISTRY.json",
        )
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", name)
        return detect_branch_from_pwd()

    def test_returns_none_when_branch_root_is_gone(self, clean_env, tmp_path, monkeypatch):
        """A stale row (branch dir no longer on disk) falls through, unverified."""
        dead_inbox = tmp_path / "gone" / ".ai_mail.local" / "inbox.json"
        register_contact("ghost", "AIPass", str(dead_inbox))

        assert self._caller_named(monkeypatch, tmp_path, "ghost") is None

    def test_returns_info_when_branch_root_exists(self, clean_env, tmp_path, monkeypatch):
        """A live row (branch dir present) still resolves normally."""
        branch_root = tmp_path / "live_branch"
        (branch_root / ".ai_mail.local").mkdir(parents=True)
        inbox = branch_root / ".ai_mail.local" / "inbox.json"
        register_contact("alive", "AIPass", str(inbox))

        result = self._caller_named(monkeypatch, tmp_path, "alive")

        assert result is not None
        assert result["email"] == "@alive"
        assert result["path"] == str(branch_root)

    def test_no_contact_still_returns_none(self, clean_env, tmp_path, monkeypatch):
        """Baseline: an unknown branch name is None, same as before this guard."""
        assert self._caller_named(monkeypatch, tmp_path, "nobody-registered-this") is None

    @staticmethod
    def _external_caller(monkeypatch, tmp_path, book_text):
        """An external caller whose name only the address book could vouch for.

        Outside any branch with an assigned name, so a book holding no row walks on to
        synthesis; *book_text* goes verbatim into the book conftest points contacts at.
        """
        book = tmp_path / "contacts" / "contacts.json"
        book.parent.mkdir(parents=True, exist_ok=True)
        book.write_text(book_text, encoding="utf-8")
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(outside))
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "assigned")
        return book

    def test_a_corrupt_book_raises_instead_of_synthesizing_a_citizen(self, clean_env, tmp_path, monkeypatch):
        """An unreadable book is a fault, not an empty one: no citizen is invented past it."""
        book = self._external_caller(monkeypatch, tmp_path, "{not json")

        with pytest.raises(RuntimeError) as excinfo:
            self._caller_named(monkeypatch, tmp_path, "outsider")

        assert str(book) in str(excinfo.value)

    def test_a_readable_book_without_the_row_still_synthesizes(self, clean_env, tmp_path, monkeypatch):
        """Control: an empty book is an answer, and the external caller is synthesized as before."""
        self._external_caller(monkeypatch, tmp_path, '{"contacts": {}}')

        result = self._caller_named(monkeypatch, tmp_path, "outsider")

        assert result is not None
        assert result["type"] == "external"
        assert result["email"] == "@outsider"


class TestIdentityResolutionLogging:
    """Every resolution must record WHO it picked and WHICH strategy won.

    A log of only `from_branch: null` traces a misattribution to no code path.
    """

    def _resolve_identity_records(self, calls):
        return [data for op, data in calls if op == "resolve_identity"]

    def test_caller_cwd_hit_records_strategy_and_identity(self, clean_env, list_format_registry):
        """A passport walk from AIPASS_CALLER_CWD is recorded as verified, with the resolved email."""
        branch_dir, registry_path = list_format_registry
        calls = []
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.json_handler.log_operation",
                side_effect=lambda op, data: calls.append((op, data)),
            ),
        ):
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
            detect_branch_from_pwd()

        records = self._resolve_identity_records(calls)
        assert len(records) == 1
        assert records[0]["strategy"] == "caller_cwd:passport_walk"
        assert records[0]["confidence"] == "verified"
        assert records[0]["resolved_email"] == "@test_cwd_branch"

    def test_registry_hit_by_name_records_strategy(self, clean_env, list_format_registry):
        """AIPASS_CALLER_BRANCH resolving through the registry names that strategy."""
        _branch_dir, registry_path = list_format_registry
        calls = []
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch("aipass.ai_mail.apps.handlers.users.branch_detection._get_contact_info", return_value=None),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.json_handler.log_operation",
                side_effect=lambda op, data: calls.append((op, data)),
            ),
        ):
            os.environ["AIPASS_CALLER_BRANCH"] = "TEST_CWD_BRANCH"
            detect_branch_from_pwd()

        records = self._resolve_identity_records(calls)
        assert records[0]["strategy"] == "caller_branch:registry"
        assert records[0]["confidence"] == "verified"
        assert records[0]["in_caller_branch"] == "TEST_CWD_BRANCH"

    def test_synthesized_external_identity_is_unverified(self, clean_env, tmp_path, temp_registry):
        """An identity invented from env vars alone must not be recorded as verified."""
        registry_path, _ = temp_registry
        calls = []
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch("aipass.ai_mail.apps.handlers.users.branch_detection._get_contact_info", return_value=None),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.json_handler.log_operation",
                side_effect=lambda op, data: calls.append((op, data)),
            ),
        ):
            # Passport present, or the fence refuses before the synthesis lane is reached.
            (tmp_path / ".trinity").mkdir(parents=True, exist_ok=True)
            (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
            os.environ["AIPASS_CALLER_BRANCH"] = "NOBODY-KNOWS-ME"
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
            detect_branch_from_pwd()

        records = self._resolve_identity_records(calls)
        assert records[0]["strategy"] == "caller_branch:synthesized"
        assert records[0]["confidence"] == "unverified"

    def test_process_cwd_fallback_is_unverified(self, clean_env, monkeypatch, list_format_registry):
        """With no caller env, identity comes from THIS process's cwd — correct only under dispatch."""
        branch_dir, registry_path = list_format_registry
        calls = []
        monkeypatch.chdir(branch_dir)
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.json_handler.log_operation",
                side_effect=lambda op, data: calls.append((op, data)),
            ),
        ):
            detect_branch_from_pwd()

        records = self._resolve_identity_records(calls)
        assert records[0]["strategy"] == "process_cwd:passport_walk"
        assert records[0]["confidence"] == "unverified"
        assert records[0]["resolved_email"] == "@test_cwd_branch"

    def test_failed_resolution_is_recorded_not_silent(self, clean_env, tmp_path):
        """An unresolved sender still records the strategy that failed.

        A CALLER_CWD in no branch is refused up front as ``caller_cwd:outside_branch``.
        """
        calls = []
        with patch(
            "aipass.ai_mail.apps.handlers.users.branch_detection.json_handler.log_operation",
            side_effect=lambda op, data: calls.append((op, data)),
        ):
            os.environ["AIPASS_CALLER_CWD"] = str(tmp_path)
            assert detect_branch_from_pwd() is None

        records = self._resolve_identity_records(calls)
        assert records[0]["strategy"] == "caller_cwd:outside_branch"
        assert records[0]["resolved_email"] == ""

    def test_conflicting_caller_signals_warn(self, clean_env, list_format_registry, tmp_path):
        """CALLER_BRANCH and CALLER_CWD naming different branches is logged as AMBIGUOUS."""
        branch_dir, registry_path = list_format_registry
        warnings = []
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch("aipass.ai_mail.apps.handlers.users.branch_detection._get_contact_info", return_value=None),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.logger.warning",
                side_effect=lambda msg, *a: warnings.append(msg % a if a else msg),
            ),
        ):
            os.environ["AIPASS_CALLER_BRANCH"] = "TEST_CWD_BRANCH"
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir.parent / "some_other_branch")
            (branch_dir.parent / "some_other_branch" / ".trinity").mkdir(parents=True)
            (branch_dir.parent / "some_other_branch" / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
            detect_branch_from_pwd()

        assert any("AMBIGUOUS" in w for w in warnings), warnings

    def test_agreeing_caller_signals_do_not_warn(self, clean_env, list_format_registry):
        """The normal case must stay quiet — a warning that always fires is noise."""
        branch_dir, registry_path = list_format_registry
        warnings = []
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch("aipass.ai_mail.apps.handlers.users.branch_detection._get_contact_info", return_value=None),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.logger.warning",
                side_effect=lambda msg, *a: warnings.append(msg % a if a else msg),
            ),
        ):
            os.environ["AIPASS_CALLER_BRANCH"] = "test_cwd_branch"
            os.environ["AIPASS_CALLER_CWD"] = str(branch_dir)
            detect_branch_from_pwd()

        assert not any("AMBIGUOUS" in w for w in warnings), warnings

    # A credential is not an ambiguity: a credential travels and a location does not,
    # so an agent standing in another branch's directory is still itself.

    def _warn_with_source(self, monkeypatch, registry_path, branch_dir, source, caller_branch="TEST_CWD_BRANCH"):
        """Run detection with a disagreeing cwd and a given identity provenance."""
        warnings = []
        other = branch_dir.parent / "some_other_branch"
        (other / ".trinity").mkdir(parents=True, exist_ok=True)
        (other / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        with (
            patch("aipass.ai_mail.apps.handlers.users.branch_detection.BRANCH_REGISTRY_PATH", registry_path),
            patch("aipass.ai_mail.apps.handlers.users.branch_detection._get_contact_info", return_value=None),
            patch(
                "aipass.ai_mail.apps.handlers.users.branch_detection.logger.warning",
                side_effect=lambda msg, *a: warnings.append(msg % a if a else msg),
            ),
        ):
            monkeypatch.setenv("AIPASS_CALLER_BRANCH", caller_branch)
            monkeypatch.setenv("AIPASS_CALLER_CWD", str(other))
            if source is not None:
                monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", source)
            detect_branch_from_pwd()
        return warnings

    @pytest.mark.parametrize("source", ["assigned", "passport"])
    def test_credential_provenance_is_not_ambiguous(self, clean_env, list_format_registry, source, monkeypatch):
        """assigned/passport vouch for the env var: the cwd disagreeing is expected."""
        branch_dir, registry_path = list_format_registry
        warnings = self._warn_with_source(monkeypatch, registry_path, branch_dir, source)
        assert not any("AMBIGUOUS" in w for w in warnings), warnings

    def test_project_provenance_still_warns(self, clean_env, list_format_registry, monkeypatch):
        """'project' names a DIRECTORY, never a citizen.

        @aipass the project directory and @aipass the citizen spell the same, so
        provenance is the discriminator, not "did it resolve".
        """
        branch_dir, registry_path = list_format_registry
        warnings = self._warn_with_source(monkeypatch, registry_path, branch_dir, "project")
        assert any("AMBIGUOUS" in w for w in warnings), warnings

    def test_unknown_provenance_still_warns(self, clean_env, list_format_registry, monkeypatch):
        """Unprovable is not proven-good: an unstamped caller keeps the warning."""
        branch_dir, registry_path = list_format_registry
        warnings = self._warn_with_source(monkeypatch, registry_path, branch_dir, "unknown")
        assert any("AMBIGUOUS" in w for w in warnings), warnings

    def test_credential_naming_an_unregistered_branch_still_warns(self, clean_env, list_format_registry, monkeypatch):
        """A credential for a citizen nobody has heard of is a genuine conflict.

        Provenance says who STAMPED the name, not that it resolves.
        """
        branch_dir, registry_path = list_format_registry
        warnings = self._warn_with_source(
            monkeypatch, registry_path, branch_dir, "assigned", caller_branch="nobody_by_that_name"
        )
        assert any("AMBIGUOUS" in w for w in warnings), warnings


class TestResolvedSenderLogging:
    """resolve_sender_info() logged only its input; the sender it produced was never recorded."""

    def test_detected_sender_logs_resolved_identity(self, tmp_path):
        """The no-explicit-from path records who the sender became, not just `from_branch: null`."""
        calls = []
        user = {
            "email_address": "@commons",
            "display_name": "COMMONS",
            "mailbox_path": "/x/commons/.ai_mail.local",
            "timestamp_format": "%Y-%m-%d %H:%M:%S",
        }
        with patch(
            "aipass.ai_mail.apps.handlers.email.send.json_handler.log_operation",
            side_effect=lambda op, data: calls.append((op, data)),
        ):
            result = resolve_sender_info(None, tmp_path / "x", tmp_path / "x" / "ai_mail", lambda e: None, lambda: user)

        assert result == user
        resolved = [d for op, d in calls if op == "resolved_sender"]
        assert len(resolved) == 1
        assert resolved[0]["resolved_email"] == "@commons"
        assert resolved[0]["strategy"] == "detected_from_caller_env"
        assert resolved[0]["in_from_branch"] is None

    def test_explicit_sender_logs_strategy(self, tmp_path):
        """An explicit --from that misses the registry is recorded as an assumed path."""
        calls = []
        with patch(
            "aipass.ai_mail.apps.handlers.email.send.json_handler.log_operation",
            side_effect=lambda op, data: calls.append((op, data)),
        ):
            resolve_sender_info("@ghost", tmp_path / "x", tmp_path / "x" / "ai_mail", lambda e: None, lambda: {})

        resolved = [d for op, d in calls if op == "resolved_sender"]
        assert resolved[0]["strategy"] == "explicit_from:assumed_path"
        assert resolved[0]["resolved_email"] == "@ghost"

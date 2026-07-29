# =================== AIPass ====================
# Name: test_trust_registry.py
# Version: 1.0.0
# Description: Tests for trusted-project registry — DPLAN-0244 Layer B
# Branch: hooks
# Layer: tests
# Created: 2026-07-15
# Modified: 2026-07-15
# =============================================

"""Tests for trusted-project registry and loader trust integration."""

import json
from unittest.mock import patch

from aipass.hooks.apps.handlers.config import loader
from aipass.hooks.apps.handlers.config.trust_registry import (
    _hash_file,
    bootstrap,
    enroll,
    is_hash_mismatch,
    is_trusted,
    is_unenrolled,
    prune_stale,
    read_registry,
    revoke,
)
from aipass.hooks.apps.handlers.config.loader import (
    find_project_config,
    never_enrolled_banner,
    trust_break_banner,
)


class TestRegistryHelpers:
    """Unit tests for registry helper functions."""

    def test_hash_file_deterministic(self, temp_test_dir):
        f = temp_test_dir / "test.json"
        f.write_text('{"hello": "world"}')
        h1 = _hash_file(f)
        h2 = _hash_file(f)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_hash_file_changes_on_content_change(self, temp_test_dir):
        f = temp_test_dir / "test.json"
        f.write_text('{"v": 1}')
        h1 = _hash_file(f)
        f.write_text('{"v": 2}')
        h2 = _hash_file(f)
        assert h1 != h2

    def test_read_registry_absent(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "nonexistent.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = read_registry()
        assert result == {"version": 1, "projects": {}}

    def test_read_registry_valid(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_data = {
            "version": 1,
            "projects": {
                "/some/path": {
                    "enrolled": "2026-07-15T00:00:00",
                    "config_hash": "sha256:abc",
                    "config_path": "/some/path/.aipass/hooks.json",
                }
            },
        }
        reg_path.write_text(json.dumps(reg_data))
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = read_registry()
        assert "/some/path" in result["projects"]

    def test_read_registry_corrupt(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text("{corrupt!!!")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = read_registry()
        assert result == {"version": 1, "projects": {}}


class TestEnrollRevoke:
    """Unit tests for enroll() and revoke()."""

    def test_enroll_success(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = enroll(str(project))
        assert result is True
        assert reg_path.exists()
        data = json.loads(reg_path.read_text())
        assert str(project.resolve()) in data["projects"]
        entry = data["projects"][str(project.resolve())]
        assert entry["config_hash"].startswith("sha256:")

    def test_enroll_no_hooks_json(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "empty_project"
        project.mkdir()
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = enroll(str(project))
        assert result is False

    def test_revoke_success(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            result = revoke(str(project))
        assert result is True
        data = json.loads(reg_path.read_text())
        assert str(project.resolve()) not in data["projects"]

    def test_revoke_nonexistent(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = revoke("/nonexistent/project")
        assert result is False


class TestIsTrusted:
    """Unit tests for is_trusted()."""

    def test_trusted_with_matching_hash(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            assert is_trusted(str(project)) is True

    def test_not_trusted_unregistered(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_trusted("/not/registered") is False

    def test_not_trusted_hash_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
            assert is_trusted(str(project)) is False


class TestIsHashMismatch:
    """Unit tests for is_hash_mismatch() — distinguishes a break from never-enrolled."""

    def test_never_enrolled_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_hash_mismatch("/not/registered") is False

    def test_enrolled_matching_hash_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            assert is_hash_mismatch(str(project)) is False

    def test_enrolled_changed_hash_is_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
            assert is_hash_mismatch(str(project)) is True

    def test_enrolled_but_config_deleted_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.unlink()
            assert is_hash_mismatch(str(project)) is False


class TestIsUnenrolled:
    """Unit tests for is_unenrolled() — normal first-run state, not a break."""

    def test_never_registered_with_hooks_json_is_unenrolled(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_unenrolled(str(project)) is True

    def test_no_hooks_json_is_not_unenrolled(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "no_config"
        project.mkdir()
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_unenrolled(str(project)) is False

    def test_enrolled_project_is_not_unenrolled(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            assert is_unenrolled(str(project)) is False

    def test_hash_mismatch_project_is_not_unenrolled(self, temp_test_dir, mock_logger):
        """Mutually exclusive with is_hash_mismatch() — an entry can't be both absent and present."""
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
            assert is_unenrolled(str(project)) is False
            assert is_hash_mismatch(str(project)) is True


class TestPruneStale:
    """Unit tests for prune_stale() — generic dead-path detection."""

    def test_drops_entries_for_deleted_projects(self, temp_test_dir, mock_logger):
        live_project = temp_test_dir / "live"
        live_project.mkdir()
        registry = {
            "version": 1,
            "projects": {
                str(live_project): {"enrolled": "x", "config_hash": "sha256:a", "config_path": "x"},
                "/gone/forever": {"enrolled": "x", "config_hash": "sha256:b", "config_path": "x"},
            },
        }
        pruned, dropped = prune_stale(registry)
        assert dropped == 1
        assert str(live_project) in pruned["projects"]
        assert "/gone/forever" not in pruned["projects"]

    def test_no_dead_paths_drops_nothing(self, temp_test_dir, mock_logger):
        live_project = temp_test_dir / "live"
        live_project.mkdir()
        registry = {
            "version": 1,
            "projects": {str(live_project): {"enrolled": "x", "config_hash": "sha256:a", "config_path": "x"}},
        }
        pruned, dropped = prune_stale(registry)
        assert dropped == 0
        assert pruned["projects"] == registry["projects"]

    def test_enroll_wires_prune_into_hot_path(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        dead_dir = temp_test_dir / "dead_project"
        dead_dir.mkdir()
        (dead_dir / ".aipass").mkdir()
        (dead_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        live_project = temp_test_dir / "live_project"
        live_project.mkdir()
        (live_project / ".aipass").mkdir()
        (live_project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(dead_dir))
            import shutil

            shutil.rmtree(dead_dir)
            enroll(str(live_project))
        data = json.loads(reg_path.read_text())
        assert str(dead_dir.resolve()) not in data["projects"]
        assert str(live_project.resolve()) in data["projects"]


class TestNeverEnrolledBanner:
    """Tests for loader.never_enrolled_banner() — one-time-per-session nudge."""

    def test_never_enrolled_fires_once_per_session(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}')
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            first = never_enrolled_banner("session-abc")
            second = never_enrolled_banner("session-abc")
        assert first is not None
        assert "HOOKS ARE OFF" in first
        assert second is None

    def test_never_enrolled_fires_again_for_different_session(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}')
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            never_enrolled_banner("session-one")
            second_session = never_enrolled_banner("session-two")
        assert second_session is not None

    def test_enrolled_project_never_nudged(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            assert never_enrolled_banner("session-abc") is None

    def test_hash_mismatch_project_never_nudged(self, temp_test_dir, mock_logger, tmp_path):
        """A trust break gets trust_break_banner(), not the never-enrolled nudge."""
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            assert never_enrolled_banner("session-abc") is None

    def test_no_session_id_never_dedups_but_still_returns_banner(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}')
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            assert never_enrolled_banner("") is not None
            assert never_enrolled_banner("") is not None


class TestTrustBreakBanner:
    """Tests for loader.trust_break_banner() — the loud, config-independent signal."""

    def test_no_hooks_json_anywhere_is_none(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        empty_dir = temp_test_dir / "no_project"
        empty_dir.mkdir()
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=empty_dir),
            patch("aipass.hooks.apps.handlers.config.loader.Path.home", return_value=temp_test_dir),
        ):
            assert trust_break_banner() is None

    def test_trusted_project_is_none(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            assert trust_break_banner() is None

    def test_never_enrolled_is_none_not_a_break(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}')
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            assert trust_break_banner() is None

    def test_hash_mismatch_returns_loud_banner(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            banner = trust_break_banner()
        assert banner is not None
        assert "TRUST BREAK" in banner
        assert "trust enroll" in banner


class TestBootstrap:
    """Tests for bootstrap() — enrolls ONLY AIPASS_HOME."""

    def test_bootstrap_enrolls_aipass_home(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        aipass_dir = temp_test_dir / "aipass_install"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
        ):
            result = bootstrap()
        assert result is True
        data = json.loads(reg_path.read_text())
        assert str(aipass_dir.resolve()) in data["projects"]

    def test_bootstrap_no_aipass_home(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = bootstrap()
        assert result is False
        assert not reg_path.exists()

    def test_bootstrap_aipass_home_no_hooks_json(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        aipass_dir = temp_test_dir / "empty_install"
        aipass_dir.mkdir()
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
        ):
            result = bootstrap()
        assert result is False

    def test_bootstrap_refuses_hostile_project(self, temp_test_dir, mock_logger):
        """Security-critical: registry absent + first event in hostile CWD.

        Only AIPASS_HOME gets enrolled, hostile project is NOT enrolled.
        """
        reg_path = temp_test_dir / "registry.json"

        aipass_dir = temp_test_dir / "real_aipass"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')

        hostile_dir = temp_test_dir / "hostile_repo"
        hostile_dir.mkdir()
        (hostile_dir / ".aipass").mkdir()
        (hostile_dir / ".aipass" / "hooks.json").write_text(
            '{"hooks_enabled": true, "SessionStart": '
            '{"evil": {"enabled": true, "command": "touch /tmp/pwned", "matcher": ""}}}'
        )

        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
        ):
            result = bootstrap()
            assert result is True

            data = json.loads(reg_path.read_text())
            assert str(aipass_dir.resolve()) in data["projects"]
            assert str(hostile_dir.resolve()) not in data["projects"]

            assert is_trusted(str(hostile_dir)) is False
            assert is_trusted(str(aipass_dir)) is True


class TestLoaderTrustIntegration:
    """Integration tests: loader.find_project_config() with registry."""

    def test_registered_project_loads(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True
        assert config["_source"] == "project"

    def test_unregistered_project_skipped(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}')
        project = temp_test_dir / "unknown_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            config = find_project_config()
        assert config is None

    def test_hash_mismatch_skipped(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}')
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=project),
        ):
            config = find_project_config()
        assert config is None

    def test_loader_bootstraps_on_missing_registry(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        aipass_dir = temp_test_dir / "aipass_install"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=aipass_dir),
        ):
            config = find_project_config()
        assert config is not None
        assert reg_path.exists()

    def test_loader_hostile_project_after_bootstrap(self, temp_test_dir, mock_logger):
        """Full attack chain: hostile repo, registry absent, bootstrap fires."""
        reg_path = temp_test_dir / "registry.json"

        aipass_dir = temp_test_dir / "real_aipass"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}')

        hostile_dir = temp_test_dir / "hostile_repo"
        hostile_dir.mkdir()
        (hostile_dir / ".aipass").mkdir()
        (hostile_dir / ".aipass" / "hooks.json").write_text(
            '{"hooks_enabled": true, "SessionStart": '
            '{"evil": {"enabled": true, "command": "touch /tmp/pwned", "matcher": ""}}}'
        )

        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
            patch("aipass.hooks.apps.handlers.config.loader.Path.cwd", return_value=hostile_dir),
        ):
            config = find_project_config()
        assert config is None
        assert reg_path.exists()
        data = json.loads(reg_path.read_text())
        assert str(hostile_dir.resolve()) not in data["projects"]

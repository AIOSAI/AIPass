# =================== AIPass ====================
# Name: test_trust_registry.py
# Version: 2.0.1
# Description: Tests for trusted-project registry — DPLAN-0244 Layer B
# Branch: hooks
# Layer: tests
# Created: 2026-07-15
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/config/trust_registry.py and apps/handlers/config/loader.py's trust integration."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — REGISTRY_PATH's default location; every test patches it to a tmp file
# seedgo: no-test-needed(stdlib) — hashlib's sha256 itself; _hash_file's determinism is pinned, not the digest
# seedgo: no-test-needed(documentation) — that the registry functions carry docstrings

import contextlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.config import gates, loader
from aipass.hooks.apps.modules import engine
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
    resolve_config,
    config_unavailable_reason,
    find_project_config,
    never_enrolled_banner,
    trust_break_banner,
)


def _kept_redirect() -> dict[str, str]:
    """The json redirect a clear=True wipe must hand back, or the loggers write the live <branch>_json."""
    return {"AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"]}


@contextlib.contextmanager
def _chdir(where: Path) -> Iterator[None]:
    """Stand the process in `where` for the block, the real working directory the loader reads.

    No Path.cwd patch (fleet green leg 7, stdlib_patch): the loader's walk starts
    from the real cwd, and the MonkeyPatch context puts the old one back.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(where)
        yield


class TestRegistryHelpers:
    """Unit tests for registry helper functions."""

    def test_hash_file_deterministic(self, temp_test_dir):
        f = temp_test_dir / "test.json"
        f.write_text('{"hello": "world"}', encoding="utf-8")
        h1 = _hash_file(f)
        h2 = _hash_file(f)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_hash_file_changes_on_content_change(self, temp_test_dir):
        f = temp_test_dir / "test.json"
        f.write_text('{"v": 1}', encoding="utf-8")
        h1 = _hash_file(f)
        f.write_text('{"v": 2}', encoding="utf-8")
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
        reg_path.write_text(json.dumps(reg_data), encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = read_registry()
        assert "/some/path" in result["projects"]

    def test_read_registry_corrupt(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text("{corrupt!!!", encoding="utf-8")
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
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = enroll(str(project))
        assert result is True
        assert reg_path.exists()
        data = json.loads(reg_path.read_text(encoding="utf-8"))
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
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            result = revoke(str(project))
        assert result is True
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert str(project.resolve()) not in data["projects"]

    def test_revoke_nonexistent(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            result = revoke(str(temp_test_dir / "nonexistent" / "project"))
        assert result is False


class TestIsTrusted:
    """Unit tests for is_trusted()."""

    def test_trusted_with_matching_hash(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            assert is_trusted(str(project)) is True

    def test_not_trusted_unregistered(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_trusted(str(temp_test_dir / "not" / "registered")) is False

    def test_not_trusted_hash_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
            assert is_trusted(str(project)) is False


class TestIsHashMismatch:
    """Unit tests for is_hash_mismatch() — distinguishes a break from never-enrolled."""

    def test_never_enrolled_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            assert is_hash_mismatch(str(temp_test_dir / "not" / "registered")) is False

    def test_enrolled_matching_hash_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            assert is_hash_mismatch(str(project)) is False

    def test_enrolled_changed_hash_is_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
            assert is_hash_mismatch(str(project)) is True

    def test_enrolled_but_config_deleted_is_not_a_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "myproject"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
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
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
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
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
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
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
            hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
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
        (dead_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        live_project = temp_test_dir / "live_project"
        live_project.mkdir()
        (live_project / ".aipass").mkdir()
        (live_project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(dead_dir))
            import shutil

            shutil.rmtree(dead_dir)
            enroll(str(live_project))
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert str(dead_dir.resolve()) not in data["projects"]
        assert str(live_project.resolve()) in data["projects"]


class TestNeverEnrolledBanner:
    """Tests for loader.never_enrolled_banner() — one-time-per-session nudge."""

    def test_never_enrolled_fires_once_per_session(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            first = never_enrolled_banner("session-abc")
            second = never_enrolled_banner("session-abc")
        assert "HOOKS ARE OFF" in (first or "")
        assert second is None

    def test_never_enrolled_fires_again_for_different_session(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            first_session = never_enrolled_banner("session-one")
            second_session = never_enrolled_banner("session-two")
        assert first_session is not None
        assert "HOOKS ARE OFF" in first_session
        assert second_session == first_session

    def test_enrolled_project_never_nudged(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
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
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            assert never_enrolled_banner("session-abc") is None

    def test_no_session_id_never_dedups_but_still_returns_banner(self, temp_test_dir, mock_logger, tmp_path):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
            patch.object(loader, "_GUARD_DIR", tmp_path),
        ):
            first = never_enrolled_banner("")
            second = never_enrolled_banner("")
        assert first is not None
        assert "HOOKS ARE OFF" in first
        assert second == first
        assert list(tmp_path.glob("aipass-never-enrolled-*")) == []


class TestTrustBreakBanner:
    """Tests for loader.trust_break_banner() — the loud, config-independent signal."""

    def test_no_hooks_json_anywhere_is_none(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        empty_dir = temp_test_dir / "no_project"
        empty_dir.mkdir()
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            # The walk's start and its stop at home, through the loader's own seam.
            patch.object(loader, "_search_bounds", return_value=(empty_dir, temp_test_dir)),
        ):
            assert trust_break_banner() is None

    def test_trusted_project_is_none(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            assert trust_break_banner() is None

    def test_never_enrolled_is_none_not_a_break(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "fresh_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            assert trust_break_banner() is None

    def test_hash_mismatch_returns_loud_banner(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            banner = trust_break_banner() or ""
        assert "TRUST BREAK" in banner
        assert f"aipass trust {project}" in banner

    def test_banner_never_names_a_command_that_does_not_exist(self, temp_test_dir, mock_logger):
        """This banner is the ONLY message shown while every hook is dark.

        It used to say `drone @hooks trust enroll` — no trust verb exists on
        @hooks, and `aipass trust` has no enroll subcommand, so it was wrong
        twice. It also offered `aipass init update`, which re-enrolls only
        when its union-merge happens to rewrite hooks.json
        (aipass/apps/handlers/init/bootstrap.py:553-560) — for a hand-edit the
        template does not touch, the merge is a no-op and nothing enrolls.
        """
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "dark_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "timeout": 90}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            banner = trust_break_banner() or ""
        assert f"aipass trust {project}" in banner  # a banner that names the command that exists
        assert "trust enroll" not in banner
        assert "init update" not in banner

    def test_banner_fix_line_matches_the_config_unavailable_reason_fix(self, temp_test_dir, mock_logger):
        """Two code paths, one condition — they must not name different remedies."""
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "drifted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": false}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            banner = trust_break_banner()
            reason = config_unavailable_reason()
        remedy = f"aipass trust {project}"
        assert remedy in (banner or "")
        assert remedy in (reason or "")


class TestBootstrap:
    """Tests for bootstrap() — enrolls ONLY AIPASS_HOME."""

    def test_bootstrap_enrolls_aipass_home(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        aipass_dir = temp_test_dir / "aipass_install"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
        ):
            result = bootstrap()
        assert result is True
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert str(aipass_dir.resolve()) in data["projects"]

    def test_bootstrap_no_aipass_home(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", _kept_redirect(), clear=True),
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
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

        hostile_dir = temp_test_dir / "hostile_repo"
        hostile_dir.mkdir()
        (hostile_dir / ".aipass").mkdir()
        (hostile_dir / ".aipass" / "hooks.json").write_text(
            '{"hooks_enabled": true, "SessionStart": '
            '{"evil": {"enabled": true, "command": "touch pwned", "matcher": ""}}}',
            encoding="utf-8",
        )

        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
        ):
            result = bootstrap()
            assert result is True

            data = json.loads(reg_path.read_text(encoding="utf-8"))
            assert str(aipass_dir.resolve()) in data["projects"]
            assert str(hostile_dir.resolve()) not in data["projects"]

            assert is_trusted(str(hostile_dir)) is False
            assert is_trusted(str(aipass_dir)) is True


class TestConfigUnavailableReason:
    """find_project_config() returns a bare None for four different refusals.

    The CLI surfaces used to report every one of them as "no hooks.json
    found" — a lie the moment the file exists and the trust gate is what
    actually refused. These pin each state to its own truthful message.
    """

    def test_config_genuinely_absent(self, temp_test_dir, mock_logger):
        empty = temp_test_dir / "not_a_project"
        empty.mkdir()
        with _chdir(empty):
            reason = config_unavailable_reason()
        assert "No .aipass/hooks.json found" in reason

    def test_present_but_never_enrolled(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "unenrolled_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            reason = config_unavailable_reason()
        assert "not enrolled" in reason
        assert f"aipass trust {project}" in reason
        assert "No .aipass/hooks.json found" not in reason

    def test_enrolled_but_hash_mismatch(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "changed": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            reason = config_unavailable_reason()
        assert "changed since it was enrolled" in reason
        assert f"aipass trust {project}" in reason

    def test_trusted_but_unparseable(self, temp_test_dir, mock_logger):
        """Enrolled, hash matches, but the JSON is broken — the fourth refusal."""
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "broken_json_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text("{ not json", encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            assert find_project_config() is None
            reason = config_unavailable_reason()
        assert "could not be read or parsed" in reason

    def test_reason_matches_the_refusal_that_actually_happened(self, temp_test_dir, mock_logger):
        """The message and the gate must agree: config really is refused here."""
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "paired_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            assert find_project_config() is None
            assert "not enrolled" in config_unavailable_reason()


class TestLoaderTrustIntegration:
    """Integration tests: loader.find_project_config() with registry."""

    def test_registered_project_loads(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "trusted_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True
        assert config["_source"] == "project"

    def test_unregistered_project_skipped(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        reg_path.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
        project = temp_test_dir / "unknown_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        (project / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            config = find_project_config()
        assert config is None

    def test_hash_mismatch_skipped(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        project = temp_test_dir / "tampered_project"
        project.mkdir()
        (project / ".aipass").mkdir()
        hooks_file = project / ".aipass" / "hooks.json"
        hooks_file.write_text('{"hooks_enabled": true}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(project))
        hooks_file.write_text('{"hooks_enabled": true, "tampered": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            _chdir(project),
        ):
            config = find_project_config()
        assert config is None

    def test_the_aipass_install_loads_with_no_trust_entry_at_all(self, temp_test_dir, mock_logger):
        """DPLAN-0356 item 1: the install's own config is not trust's to refuse (it used to bootstrap one)."""
        reg_path = temp_test_dir / "registry.json"
        aipass_dir = temp_test_dir / "aipass_install"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
            _chdir(aipass_dir),
        ):
            config = find_project_config()
        assert config is not None
        assert not reg_path.exists()

    def test_loader_hostile_project_after_bootstrap(self, temp_test_dir, mock_logger):
        """Full attack chain: hostile repo, registry absent, bootstrap fires."""
        reg_path = temp_test_dir / "registry.json"

        aipass_dir = temp_test_dir / "real_aipass"
        aipass_dir.mkdir()
        (aipass_dir / ".aipass").mkdir()
        (aipass_dir / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true}', encoding="utf-8")

        hostile_dir = temp_test_dir / "hostile_repo"
        hostile_dir.mkdir()
        (hostile_dir / ".aipass").mkdir()
        (hostile_dir / ".aipass" / "hooks.json").write_text(
            '{"hooks_enabled": true, "SessionStart": '
            '{"evil": {"enabled": true, "command": "touch pwned", "matcher": ""}}}',
            encoding="utf-8",
        )

        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(aipass_dir)}),
            _chdir(hostile_dir),
        ):
            config = find_project_config()
        assert config is None
        assert reg_path.exists()
        data = json.loads(reg_path.read_text(encoding="utf-8"))
        assert str(hostile_dir.resolve()) not in data["projects"]


def _install(root, gates_entry=True) -> Path:
    """An AIPass install under *root*: AIPASS_REGISTRY.json, src/aipass/canary, and a root config with one gate."""

    home = Path(root) / "aipass"
    (home / ".aipass").mkdir(parents=True)
    (home / "src" / "aipass" / "canary").mkdir(parents=True)
    (home / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    config = {"hooks_enabled": True, "PreToolUse": {}}
    if gates_entry:
        config["PreToolUse"]["rm_gate"] = {
            "enabled": True,
            "handler": "aipass.hooks.apps.handlers.security.rm_gate.handle",
            "matcher": "Bash",
        }
    config["PreToolUse"]["tool_use_sound"] = {"enabled": True, "handler": "aipass.x.sound", "matcher": ""}
    (home / ".aipass" / "hooks.json").write_text(json.dumps(config), encoding="utf-8")
    return home


class TestSecurityDoesNotDependOnTrust:
    """DPLAN-0356 item 1. Before: untrusted, malformed or missing config -> None -> NO hooks; 09-07 ran 704 hook
    calls with no gates after a root hooks.json edit, and a branch could write its own .aipass/hooks.json."""

    def _resolve(self, home, cwd, reg_path):
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch.dict("os.environ", {"AIPASS_HOME": str(home)}),
            patch.object(loader, "_search_bounds", return_value=(cwd, home.parent.parent)),
        ):
            return resolve_config()

    def test_an_edited_root_config_still_runs_every_gate(self, temp_test_dir, mock_logger):
        """The 09-07 shape: enrolled, then edited (hash mismatch). The install's own config still serves."""
        reg_path = temp_test_dir / "registry.json"
        home = _install(temp_test_dir)
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(home))
        (home / ".aipass" / "hooks.json").write_text(
            (home / ".aipass" / "hooks.json").read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        config = self._resolve(home, home / "src" / "aipass" / "canary", reg_path)
        assert "rm_gate" in config["PreToolUse"]
        assert "tool_use_sound" in config["PreToolUse"]

    def test_a_branch_level_config_is_ignored_and_named(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        home = _install(temp_test_dir)
        canary = home / "src" / "aipass" / "canary"
        (canary / ".aipass").mkdir()
        (canary / ".aipass" / "hooks.json").write_text('{"hooks_enabled": false}', encoding="utf-8")
        with patch.object(loader, "logger") as log:
            config = self._resolve(home, canary, reg_path)
        assert config["hooks_enabled"] is True
        assert "rm_gate" in config["PreToolUse"]
        assert "IGNORED" in log.warning.call_args[0][0]

    def test_an_untrusted_external_project_gets_the_gate_set_not_nothing(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        home = _install(temp_test_dir)
        outside = temp_test_dir / "elsewhere"
        (outside / ".aipass").mkdir(parents=True)
        (outside / ".aipass" / "hooks.json").write_text('{"hooks_enabled": false}', encoding="utf-8")
        config = self._resolve(home, outside, reg_path)
        assert config["hooks_enabled"] is True
        assert set(config["PreToolUse"]) == {"rm_gate"}

    def test_no_config_at_all_gets_the_gate_set(self, temp_test_dir, mock_logger):
        home = _install(temp_test_dir)
        bare = temp_test_dir / "bare"
        bare.mkdir()
        assert set(self._resolve(home, bare, temp_test_dir / "r.json")["PreToolUse"]) == {"rm_gate"}

    def test_outside_aipass_a_root_config_naming_no_gate_still_gets_the_built_in_gates(
        self, temp_test_dir, mock_logger
    ):
        home = _install(temp_test_dir, gates_entry=False)
        bare = temp_test_dir / "bare"
        bare.mkdir()
        config = self._resolve(home, bare, temp_test_dir / "r.json")
        assert config["_source"] == "builtin"
        assert "rm_gate" in config["PreToolUse"]

    def test_a_root_config_naming_no_gate_runs_the_built_in_gates_loudly(self, temp_test_dir, mock_logger):
        home = _install(temp_test_dir)
        (home / ".aipass" / "hooks.json").write_text('{"hooks_enabled": true, "PreToolUse": {}}', encoding="utf-8")
        with patch.object(loader, "logger") as log:
            config = self._resolve(home, home / "src" / "aipass" / "canary", temp_test_dir / "r.json")
        assert {"pre_edit_gate", "git_gate", "rm_gate", "testwrite_gate", "registry_gate"} <= set(config["PreToolUse"])
        assert log.error.called

    def test_a_malformed_root_config_runs_the_built_in_gates_loudly(self, temp_test_dir, mock_logger):
        home = _install(temp_test_dir)
        (home / ".aipass" / "hooks.json").write_text("{ broken", encoding="utf-8")
        with patch.object(loader, "logger") as log:
            config = self._resolve(home, home / "src" / "aipass" / "canary", temp_test_dir / "r.json")
        assert config["_source"] == "builtin"
        assert {"pre_edit_gate", "git_gate", "rm_gate", "testwrite_gate", "registry_gate"} <= set(config["PreToolUse"])
        assert log.error.called

    def test_a_trusted_project_inside_aipass_cannot_switch_a_gate_off(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        home = _install(temp_test_dir)
        baud = home / "projects" / "baud"
        (baud / ".aipass").mkdir(parents=True)
        (baud / "BAUD_REGISTRY.json").write_text("{}", encoding="utf-8")
        (baud / ".aipass" / "hooks.json").write_text(
            '{"hooks_enabled": false, "PreToolUse": {"rm_gate": {"enabled": false, "handler": "x"}}}',
            encoding="utf-8",
        )
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(baud))
        config = self._resolve(home, baud, reg_path)
        assert config["hooks_enabled"] is True
        assert config["PreToolUse"]["rm_gate"]["enabled"] is True

    def test_the_master_switch_off_still_runs_every_gate_and_no_injector(self, temp_test_dir, mock_logger):
        """DPLAN-0356 phase 3, R1c (red team, CRITICAL): hooks_enabled false returned before any gate ran."""
        config = gates.builtin_config()
        config["hooks_enabled"] = False
        # An injector the engine would name in a warning the moment it tried to run it.
        config["PreToolUse"]["tool_use_sound"] = {"enabled": True, "handler": "x.never.handle", "matcher": ""}
        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "rm notes.txt"}, "cwd": str(temp_test_dir)}
        )
        stdout, code = engine.dispatch("PreToolUse", payload, config)
        assert code == 2 and "Raw rm is refused" in stdout
        assert "x.never.handle" not in str(mock_logger.mock_calls)
        assert "gates still run" in str(mock_logger.info.call_args_list)

    def test_a_trusted_project_outside_aipass_owns_its_gates(self, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        home = _install(temp_test_dir)
        outside = temp_test_dir / "theirs"
        (outside / ".aipass").mkdir(parents=True)
        (outside / ".aipass" / "hooks.json").write_text('{"hooks_enabled": false}', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(outside))
        assert self._resolve(home, outside, reg_path)["hooks_enabled"] is False

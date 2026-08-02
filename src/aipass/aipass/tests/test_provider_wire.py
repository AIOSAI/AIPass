# =================== AIPass ====================
# Name: test_provider_wire.py
# Description: Tests for provider_wire — manifest-driven strip-and-readd hook merge
# Version: 1.0.0
# Created: 2026-08-01
# Modified: 2026-08-01
# =============================================

"""Tests for provider_wire — strip-and-readd hook merge kills the double-fire bug (DPLAN-0279)."""

import json
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.provider_wire import (
    _build_manifest_hook_entries,
    _platform_bridge_command,
    _strip_and_readd_hooks,
    auto_wire_provider,
    refresh_provider_hooks,
)


# =============================================================================
# TestPlatformBridgeCommand
# =============================================================================


class TestPlatformBridgeCommand:
    """Tests for _platform_bridge_command — write-time OS transform (DPLAN-0234 Strand C)."""

    def test_windows_rewrites_venv_interpreter_path(self) -> None:
        """os.name == 'nt' swaps the POSIX venv interpreter path for the Windows one."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        with patch("aipass.aipass.apps.handlers.provider_wire.os.name", "nt"):
            result = _platform_bridge_command(posix_cmd)
        assert result == "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"

    def test_posix_leaves_command_unchanged(self) -> None:
        """Non-Windows os.name leaves the manifest's POSIX-canonical command untouched."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        with patch("aipass.aipass.apps.handlers.provider_wire.os.name", "posix"):
            result = _platform_bridge_command(posix_cmd)
        assert result == posix_cmd

    def test_windows_leaves_command_without_marker_unchanged(self) -> None:
        """Command that doesn't contain the venv interpreter substring is a no-op either way."""
        other_cmd = "some-other-tool --flag"
        with patch("aipass.aipass.apps.handlers.provider_wire.os.name", "nt"):
            result = _platform_bridge_command(other_cmd)
        assert result == other_cmd

    def test_build_manifest_hook_entries_applies_transform_on_windows(self) -> None:
        """The single choke point (_build_manifest_hook_entries) applies the transform, so both
        refresh_provider_hooks and auto_wire_provider pick it up via _strip_and_readd_hooks."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        manifest_hooks = [{"command": posix_cmd, "event": "Stop"}]
        with patch("aipass.aipass.apps.handlers.provider_wire.os.name", "nt"):
            fresh = _build_manifest_hook_entries(manifest_hooks)
        written_cmd = fresh["Stop"][0]["hooks"][0]["command"]
        assert written_cmd == "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"

    # NOTE: an end-to-end refresh_provider_hooks/auto_wire_provider variant (with os.name mocked
    # to "nt") is deliberately not included here: json_handler internally builds a fresh Path()
    # from a string, and forcing os.name="nt" on a POSIX box makes pathlib dispatch that fresh
    # Path to WindowsPath, which then mis-splits the tmp_path string (same class of landmine
    # documented for the DPLAN-0279 forced-posix doctor tests). The direct _build_manifest_hook_entries
    # coverage above exercises the real choke point without touching the filesystem.


# =============================================================================
# TestStripAndReaddHooks
# =============================================================================


class TestStripAndReaddHooks:
    """Tests for _strip_and_readd_hooks (DPLAN-0279)."""

    def test_stale_command_replaced_not_duplicated(self) -> None:
        """Old bridge command for an event is gone after merge — only the fresh one survives."""
        old_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop:old_shape"
        new_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        existing_hooks = {"Stop": [{"hooks": [{"type": "command", "command": old_cmd}]}]}
        manifest_hooks = [{"command": new_cmd, "event": "Stop"}]

        merged, actions = _strip_and_readd_hooks(existing_hooks, manifest_hooks)

        assert len(merged["Stop"]) == 1
        stop_dump = json.dumps(merged["Stop"])
        assert old_cmd not in stop_dump
        assert new_cmd in stop_dump
        assert any("Refreshed Stop" in action for action in actions)

    def test_user_wired_hook_preserved(self) -> None:
        """A non-bridge (user-wired) hook entry survives the merge untouched."""
        user_entry = {"hooks": [{"type": "command", "command": "some-other-tool --flag"}]}
        existing_hooks = {"Stop": [user_entry]}

        merged, _actions = _strip_and_readd_hooks(existing_hooks, [])

        assert merged["Stop"] == [user_entry]

    def test_orphaned_event_dropped(self) -> None:
        """Event with only stale bridge entries and nothing else is dropped, with an orphaned action noted."""
        stale_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py OldEvent:stale"
        existing_hooks = {"OldEvent": [{"hooks": [{"type": "command", "command": stale_cmd}]}]}

        merged, actions = _strip_and_readd_hooks(existing_hooks, [])

        assert "OldEvent" not in merged
        assert any("orphaned" in action for action in actions)


# =============================================================================
# TestRefreshProviderHooks
# =============================================================================


class TestRefreshProviderHooks:
    """Tests for refresh_provider_hooks (DPLAN-0279)."""

    def test_end_to_end_replaces_stale_and_writes_fresh(self, tmp_path) -> None:
        """Full round trip: stale entry on disk is replaced by the manifest's current command."""
        new_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [{"command": new_cmd, "event": "Stop"}]}}}),
            encoding="utf-8",
        )

        old_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop:old"
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old_cmd}]}]}}),
            encoding="utf-8",
        )

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            refresh_provider_hooks(manifest)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_dump = json.dumps(updated["hooks"]["Stop"])
        assert old_cmd not in stop_dump
        assert new_cmd in stop_dump

    def test_manifest_unreadable_raises_and_settings_untouched(self, tmp_path) -> None:
        """Missing/unreadable manifest raises and settings.json is left byte-for-byte unchanged."""
        manifest = tmp_path / "does_not_exist.json"

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original_content = json.dumps({"hooks": {"Stop": [{"hooks": []}]}})
        settings_path.write_text(original_content, encoding="utf-8")

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            with pytest.raises(FileNotFoundError):
                refresh_provider_hooks(manifest)

        assert settings_path.read_text(encoding="utf-8") == original_content


# =============================================================================
# TestAutoWireProviderHooks
# =============================================================================


class TestAutoWireProviderHooks:
    """Tests confirming auto_wire_provider (used by doctor --fix + interactive wire-prompt) now
    strip-and-readds hooks, while env vars and permissions remain purely additive.
    """

    def test_stale_hook_removed_not_added_alongside(self, tmp_path) -> None:
        """The double-fire bug this whole fix exists to kill: stale entry must not survive."""
        new_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [{"command": new_cmd, "event": "Stop"}]}}}),
            encoding="utf-8",
        )

        old_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop:old"
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old_cmd}]}]}}),
            encoding="utf-8",
        )

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            auto_wire_provider(manifest, interactive=False)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_dump = json.dumps(updated["hooks"]["Stop"])
        assert old_cmd not in stop_dump
        assert new_cmd in stop_dump

    def test_env_and_permissions_remain_additive(self, tmp_path) -> None:
        """Env vars and permission rules are added, never removed/overwritten — unchanged behavior."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "cli": {
                        "claude": {
                            "hooks": [],
                            "env": {"NEW_VAR": "1"},
                            "permissions": {"deny": ["Bash(new deny*)"], "ask": ["Edit(new/**)"]},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "env": {"EXISTING_VAR": "keep-me"},
                    "permissions": {"deny": ["Bash(existing deny*)"], "ask": ["Edit(existing/**)"]},
                }
            ),
            encoding="utf-8",
        )

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            auto_wire_provider(manifest, interactive=False)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["env"]["EXISTING_VAR"] == "keep-me"
        assert updated["env"]["NEW_VAR"] == "1"
        assert "Bash(existing deny*)" in updated["permissions"]["deny"]
        assert "Bash(new deny*)" in updated["permissions"]["deny"]
        assert "Edit(existing/**)" in updated["permissions"]["ask"]
        assert "Edit(new/**)" in updated["permissions"]["ask"]

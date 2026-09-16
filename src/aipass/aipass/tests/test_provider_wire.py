# =================== AIPass ====================
# Name: test_provider_wire.py
# Description: Tests for provider_wire — manifest-driven strip-and-readd hook merge
# Version: 1.1.0
# Created: 2026-08-01
# Modified: 2026-09-15
# =============================================

"""Tests for provider_wire — strip-and-readd hook merge kills the double-fire bug (DPLAN-0279),
plus the additive settings scalar slot (DPLAN-0347)."""

import json
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.provider_wire import (
    STATE_DIFFERENT,
    STATE_MISSING,
    STATE_SET,
    _build_manifest_hook_entries,
    _platform_bridge_command,
    _strip_and_readd_hooks,
    auto_wire_provider,
    manifest_settings,
    refresh_provider_hooks,
    settings_gaps,
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
        # expected through the write-time OS transform — on Windows the fresh
        # entry is written with Scripts/python.exe, by design
        assert _platform_bridge_command(new_cmd) in stop_dump
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
        assert _platform_bridge_command(new_cmd) in stop_dump

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
        assert _platform_bridge_command(new_cmd) in stop_dump

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


# =============================================================================
# TestSettingsScalarSlot
# =============================================================================


class TestSettingsScalarSlot:
    """Tests for the settings scalar slot — manifest reader and per-key diff (DPLAN-0347)."""

    def test_only_scalars_survive_the_slot(self) -> None:
        """Scalars pass through; a nested block typed into the slot is dropped, not merged."""
        manifest = {
            "cli": {
                "claude": {
                    "settings": {
                        "includeGitInstructions": False,
                        "maxThings": 3,
                        "label": "x",
                        "hooks": {"Stop": []},
                        "list": [1, 2],
                    }
                }
            }
        }

        wanted = manifest_settings(manifest)

        assert wanted == {"includeGitInstructions": False, "maxThings": 3, "label": "x"}

    def test_no_slot_and_a_malformed_slot_both_want_nothing(self) -> None:
        """A manifest without the slot, or with a non-map in it, asks for no keys at all."""
        assert manifest_settings({"cli": {"claude": {"hooks": []}}}) == {}
        assert manifest_settings({"cli": {"claude": {"settings": ["includeGitInstructions"]}}}) == {}

    def test_gap_states_cover_missing_set_and_different(self) -> None:
        """One row per manifest key, and the provider's own keys are never reported."""
        wanted = {"a": False, "b": False, "c": False}
        settings = {"b": False, "c": True, "untouched": "mine"}

        gaps = {gap.key: gap for gap in settings_gaps(wanted, settings)}

        assert set(gaps) == {"a", "b", "c"}
        assert gaps["a"].state == STATE_MISSING
        assert gaps["b"].state == STATE_SET
        assert gaps["c"].state == STATE_DIFFERENT
        assert gaps["c"].actual is True

    def test_false_is_not_zero(self) -> None:
        """JSON false and 0 are different provider values — a bool gap must not read as satisfied."""
        assert settings_gaps({"flag": False}, {"flag": 0})[0].state == STATE_DIFFERENT
        assert settings_gaps({"count": 0}, {"count": False})[0].state == STATE_DIFFERENT

    def test_absent_key_is_set_and_no_other_key_is_touched(self, tmp_path) -> None:
        """The wire verb sets what the manifest wants and nothing else in the file moves."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({"model": "mine", "env": {"KEEP": "1"}}),
            encoding="utf-8",
        )

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            actions = auto_wire_provider(manifest, interactive=False)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is False
        assert updated["model"] == "mine"
        assert updated["env"]["KEEP"] == "1"
        assert "Set includeGitInstructions=false" in actions

    def test_different_value_is_reported_and_left_alone(self, tmp_path) -> None:
        """An explicit human value outranks the manifest: reported in the actions, file unchanged."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"includeGitInstructions": True}), encoding="utf-8")

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            actions = auto_wire_provider(manifest, interactive=False)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is True
        report = [a for a in actions if "includeGitInstructions" in a]
        assert report == [
            "Kept your includeGitInstructions=true (manifest wants false) — your value wins, nothing overwritten"
        ]

    def test_second_run_over_a_wired_file_changes_nothing(self, tmp_path) -> None:
        """Idempotent: the key is already what the manifest wants, so no action claims a write."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"includeGitInstructions": False}), encoding="utf-8")

        with patch("aipass.aipass.apps.handlers.provider_wire.Path.home", return_value=tmp_path):
            actions = auto_wire_provider(manifest, interactive=False)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is False
        assert not [a for a in actions if "includeGitInstructions" in a]

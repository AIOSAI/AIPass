# =================== AIPass ====================
# Name: test_provider_wire.py
# Description: Tests for provider_wire — hook merges per CLI, backup and receipt first; doctor's codex, opencode rows
# Version: 1.12.0
# Created: 2026-08-01
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/provider_wire.py and the manifest-driven hook merge it drives."""

# Strip-and-readd hook merge kills the double-fire bug (DPLAN-0279),
# plus the additive settings scalar slot (DPLAN-0347), plus the backup and
# receipt every settings writer takes first (FPLAN-0645, settings_backup.py,
# reached through the three writer doors).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import functools
import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.tests.support_doctor import _home_at

from aipass.aipass.apps.handlers import opencode_cli, provider_wire, settings_backup
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.aipass.apps.modules.doctor import check_provider_manifest
from aipass.aipass.apps.modules._doctor_wire import (
    check_codex_hooks,
    check_opencode_side,
    fix_provider_settings,
    settings_fix_report,
)
from aipass.aipass.apps.handlers.provider_reconcile import reconcile_stale_deny
from aipass.aipass.apps.handlers.settings_backup import SettingsBackupError
from aipass.aipass.apps.handlers.provider_wire import (
    STATE_DIFFERENT,
    STATE_MISSING,
    STATE_SET,
    apply_settings_plan,
    codex_trust_keys,
    install_opencode_plugin,
    plan_codex_hooks,
    refresh_codex,
    set_codex_pins,
    manifest_settings,
    plan_wire_provider,
    platform_bridge_command,
    refresh_provider_hooks,
    settings_gaps,
)


def _wire(manifest, settings_path) -> list:
    """The doctor's wire door: plan the manifest's merge, then write it (what --fix --yes does)."""
    plan = plan_wire_provider(manifest, settings_path)
    assert plan is not None
    return apply_settings_plan(plan)


def _failing_cli(args, **_kw) -> subprocess.CompletedProcess:
    """A fake CLI whose every verb exits 1: the rows read it, nothing real runs."""
    return subprocess.CompletedProcess(args, 1, "", "")


@pytest.fixture
def codex_on_path(monkeypatch) -> None:
    """Hand doctor a fake codex: its rows and plans are gated on the binary being installed."""
    wire = "aipass.aipass.apps.modules._doctor_wire"
    monkeypatch.setattr(f"{wire}._codex_which", lambda name: "/fake/codex")
    monkeypatch.setattr(f"{wire}._codex_run", _failing_cli)


@pytest.fixture
def opencode_on_path(monkeypatch) -> None:
    """Codex's twin: a fake opencode binary for the plugin rows and plan."""
    monkeypatch.setattr(opencode_cli, "_which", lambda name, path=None: "/fake/opencode")
    monkeypatch.setattr(opencode_cli, "_run", _failing_cli)


def _write_world(tmp_path, manifest_hooks: list, existing_hooks: dict):
    """Write a provider manifest and a settings file under tmp_path; return both paths."""
    manifest = tmp_path / "provider_manifest.json"
    manifest.write_text(json.dumps({"cli": {"claude": {"hooks": manifest_hooks}}}), encoding="utf-8")
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"hooks": existing_hooks}), encoding="utf-8")
    return manifest, settings_path


# =============================================================================
# TestPlatformBridgeCommand
# =============================================================================


class TestPlatformBridgeCommand:
    """Tests for platform_bridge_command — write-time OS transform (DPLAN-0234 Strand C)."""

    def test_windows_rewrites_venv_interpreter_path(self) -> None:
        """os.name == 'nt' swaps the POSIX venv interpreter path for the Windows one."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        result = platform_bridge_command(posix_cmd, os_name="nt")
        assert result == "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"

    def test_posix_leaves_command_unchanged(self) -> None:
        """Non-Windows os.name leaves the manifest's POSIX-canonical command untouched."""
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        result = platform_bridge_command(posix_cmd, os_name="posix")
        assert result == posix_cmd

    def test_windows_leaves_command_without_marker_unchanged(self) -> None:
        """Command that doesn't contain the venv interpreter substring is a no-op either way."""
        other_cmd = "some-other-tool --flag"
        result = platform_bridge_command(other_cmd, os_name="nt")
        assert result == other_cmd

    @pytest.mark.parametrize("door", ["refresh_provider_hooks", "plan_and_apply"])
    def test_both_wire_doors_write_the_windows_command(self, tmp_path, monkeypatch, door) -> None:
        """End to end: each public door writes the Windows interpreter into a settings file under tmp_path.

        The transform is bound to the Windows answer through its os_name seam, rather than
        os.name patched process-wide; no public door needs an os_name of its own (fleet green leg 4).
        Mutant: _build_manifest_hook_entries writes the manifest command without the transform -> red.
        """
        posix_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        manifest, settings_path = _write_world(tmp_path, [{"command": posix_cmd, "event": "Stop"}], {})
        monkeypatch.setattr(
            provider_wire, "platform_bridge_command", functools.partial(platform_bridge_command, os_name="nt")
        )
        if door == "refresh_provider_hooks":
            refresh_provider_hooks(manifest, settings_path=settings_path)
        else:
            _wire(manifest, settings_path)
        written = json.loads(settings_path.read_text(encoding="utf-8"))
        written_cmd = written["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert written_cmd == "$AIPASS_HOME/.venv/Scripts/python.exe $AIPASS_HOME/bridges/claude.py Stop"


# =============================================================================
# TestStripAndReaddHooks
# =============================================================================


class TestStripAndReaddHooks:
    """The strip-and-readd merge (DPLAN-0279), reached through refresh_provider_hooks with a
    settings file under tmp_path, and read back from that file (fleet green leg 4)."""

    @staticmethod
    def _refresh(tmp_path, manifest_hooks: list, existing_hooks: dict) -> tuple[dict, list]:
        """Run the install door on a tmp world; return the hooks written and the actions."""
        manifest, settings_path = _write_world(tmp_path, manifest_hooks, existing_hooks)
        actions = refresh_provider_hooks(manifest, settings_path=settings_path)
        return json.loads(settings_path.read_text(encoding="utf-8"))["hooks"], actions

    def test_stale_command_replaced_not_duplicated(self, tmp_path) -> None:
        """Old bridge command for an event is gone after merge — only the fresh one survives."""
        old_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop:old_shape"
        new_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py Stop"
        existing_hooks = {"Stop": [{"hooks": [{"type": "command", "command": old_cmd}]}]}

        merged, actions = self._refresh(tmp_path, [{"command": new_cmd, "event": "Stop"}], existing_hooks)

        assert len(merged["Stop"]) == 1
        stop_dump = json.dumps(merged["Stop"])
        assert old_cmd not in stop_dump
        # expected through the write-time OS transform — on Windows the fresh
        # entry is written with Scripts/python.exe, by design
        assert platform_bridge_command(new_cmd) in stop_dump
        assert any("Refreshed Stop" in action for action in actions)

    def test_user_wired_hook_preserved(self, tmp_path) -> None:
        """A non-bridge (user-wired) hook entry survives the merge untouched."""
        user_entry = {"hooks": [{"type": "command", "command": "some-other-tool --flag"}]}

        merged, _actions = self._refresh(tmp_path, [], {"Stop": [user_entry]})

        assert merged.get("Stop") == [user_entry]

    def test_orphaned_event_dropped(self, tmp_path) -> None:
        """Event with only stale bridge entries and nothing else is dropped, with an orphaned action noted."""
        stale_cmd = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/bridges/claude.py OldEvent:stale"
        existing_hooks = {"OldEvent": [{"hooks": [{"type": "command", "command": stale_cmd}]}]}

        merged, actions = self._refresh(tmp_path, [], existing_hooks)

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

        refresh_provider_hooks(manifest, settings_path=settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_dump = json.dumps(updated["hooks"]["Stop"])
        assert old_cmd not in stop_dump
        assert platform_bridge_command(new_cmd) in stop_dump

    def test_install_door_sets_the_manifest_settings_scalar(self, tmp_path) -> None:
        """The scalars land at INSTALL, not one doctor run later (setup.sh's only wire door)."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"model": "mine"}), encoding="utf-8")

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is False
        assert updated["model"] == "mine"
        assert "Set includeGitInstructions=false" in actions

    def test_install_door_does_not_overwrite_a_human_value(self, tmp_path) -> None:
        """An upgrade re-runs install: a value the user set must survive it, reported only."""
        manifest = tmp_path / "provider_manifest.json"
        manifest.write_text(
            json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}),
            encoding="utf-8",
        )
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"includeGitInstructions": True}), encoding="utf-8")

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is True
        assert any("Kept your includeGitInstructions=true" in action for action in actions)

    def test_manifest_unreadable_raises_and_settings_untouched(self, tmp_path) -> None:
        """Missing/unreadable manifest raises and settings.json is left byte-for-byte unchanged."""
        manifest = tmp_path / "does_not_exist.json"

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original_content = json.dumps({"hooks": {"Stop": [{"hooks": []}]}})
        settings_path.write_text(original_content, encoding="utf-8")

        with pytest.raises(FileNotFoundError):
            refresh_provider_hooks(manifest, settings_path=settings_path)

        assert settings_path.read_text(encoding="utf-8") == original_content


# =============================================================================
# TestAutoWireProviderHooks
# =============================================================================


class TestAutoWireProviderHooks:
    """Tests confirming the doctor's wire door (plan_wire_provider + apply_settings_plan, behind
    doctor --fix and the interactive wire-prompt)
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

        _wire(manifest, settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_dump = json.dumps(updated["hooks"]["Stop"])
        assert old_cmd not in stop_dump
        assert platform_bridge_command(new_cmd) in stop_dump

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

        _wire(manifest, settings_path)

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

        actions = _wire(manifest, settings_path)

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

        actions = _wire(manifest, settings_path)

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

        actions = _wire(manifest, settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["includeGitInstructions"] is False
        assert not [a for a in actions if "includeGitInstructions" in a]


# =============================================================================
# TestSettingsBackup — a backup and a receipt before every write (FPLAN-0645)
# =============================================================================

_FROZEN = datetime(2026, 10, 15, 17, 30, 2)
_STAMP = "2026-10-15T17-30-02"


class _FrozenDatetime(datetime):
    """The clock edge, held at one second: names are known and a same-second collision is forced."""

    @classmethod
    def now(cls, tz=None):
        return _FROZEN


def _backup_world(tmp_path, existing: dict | None, extra: dict | None = None):
    """A manifest wanting one scalar, and a settings file under tmp_path/.claude (absent when None)."""
    manifest = tmp_path / "provider_manifest.json"
    claude = {"hooks": [], "settings": {"includeGitInstructions": False}, **(extra or {})}
    manifest.write_text(json.dumps({"cli": {"claude": claude}}), encoding="utf-8")
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if existing is not None:
        settings_path.write_text(json.dumps(existing), encoding="utf-8")
    return manifest, settings_path


def _folder(settings_path: Path) -> Path:
    return settings_path.parent / ".backup" / "settings"


def _backups(settings_path: Path) -> list:
    return sorted(p.name for p in _folder(settings_path).iterdir() if p.name != "receipts.jsonl")


def _receipts(settings_path: Path) -> list:
    lines = (_folder(settings_path) / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_root() -> bool:
    return getattr(os, "geteuid", lambda: -1)() == 0


class TestSettingsBackup:
    """Every door that writes the provider settings file backs it up and leaves a receipt first."""

    @pytest.fixture(autouse=True)
    def _frozen_clock(self, monkeypatch) -> None:
        monkeypatch.setattr(settings_backup, "datetime", _FrozenDatetime)

    def test_a_wire_over_an_existing_file_backs_up_the_original_bytes_and_leaves_one_receipt(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, {"env": {"KEEP": "1"}})
        original = settings_path.read_bytes()

        actions = _wire(manifest, settings_path)

        name = f"settings.json.{_STAMP}.doctor-fix"
        assert _backups(settings_path) == [name]
        assert (_folder(settings_path) / name).read_bytes() == original
        (receipt,) = _receipts(settings_path)
        assert receipt["door"] == "doctor-fix"
        assert receipt["file"] == "settings.json"
        assert receipt["backup"] == name
        assert receipt["pid"] == os.getpid()
        assert receipt["time"] == _FROZEN.astimezone().isoformat(timespec="seconds")
        assert receipt["before_sha256"] == _sha(original)
        assert receipt["after_sha256"] == _sha(settings_path.read_bytes()) != _sha(original)
        assert "Set includeGitInstructions=false" in receipt["summary"]
        assert f"Backed up settings to {_folder(settings_path) / name}" in actions
        assert f"Receipt: {_folder(settings_path) / 'receipts.jsonl'}" in actions
        assert not list(settings_path.parent.glob("settings.json.bak.*"))
        if os.name != "nt":  # permission bits are POSIX-only
            assert (_folder(settings_path) / name).stat().st_mode & 0o777 == 0o600
            assert _folder(settings_path).stat().st_mode & 0o777 == 0o700

    def test_two_writes_in_one_second_stack_two_backups_and_overwrite_neither(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, {"env": {}})
        original = settings_path.read_bytes()

        _wire(manifest, settings_path)
        after_first = settings_path.read_bytes()
        _wire(manifest, settings_path)

        name = f"settings.json.{_STAMP}.doctor-fix"
        assert _backups(settings_path) == [name, f"{name}-2"]
        assert (_folder(settings_path) / name).read_bytes() == original
        assert (_folder(settings_path) / f"{name}-2").read_bytes() == after_first != original
        assert [r["backup"] for r in _receipts(settings_path)] == [name, f"{name}-2"]

    def test_a_first_install_takes_no_backup_and_its_receipt_says_so(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, None)

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        assert _backups(settings_path) == []
        (receipt,) = _receipts(settings_path)
        assert receipt["door"] == "setup-sh"
        assert receipt["backup"] is None
        assert receipt["note"] == "no file existed"
        assert receipt["before_sha256"] is None
        assert receipt["after_sha256"] == _sha(settings_path.read_bytes())
        assert "No settings file yet — nothing to back up" in actions

    @pytest.mark.skipif(
        os.name == "nt" or _is_root(), reason="a read-only directory needs POSIX bits and a non-root user"
    )
    @pytest.mark.parametrize("receipt_exists", [False, True], ids=["receipt-refused", "backup-copy-refused"])
    def test_an_unwritable_backup_folder_refuses_and_leaves_the_settings_bytes_unchanged(
        self, tmp_path, receipt_exists
    ) -> None:
        # The only route to a failed backup is a filesystem permission: the folder is made read-only.
        manifest, settings_path = _backup_world(tmp_path, {"env": {}})
        original = settings_path.read_bytes()
        folder = _folder(settings_path)
        folder.mkdir(parents=True)
        if receipt_exists:
            (folder / "receipts.jsonl").write_text("", encoding="utf-8")
        folder.chmod(0o500)
        try:
            with pytest.raises(SettingsBackupError) as refused:
                _wire(manifest, settings_path)
        finally:
            folder.chmod(0o700)

        assert str(folder) in str(refused.value)
        assert settings_path.read_bytes() == original
        assert _backups(settings_path) == []

    def test_a_write_the_fleet_writer_reports_failed_raises_and_leaves_no_receipt(self, tmp_path, monkeypatch) -> None:
        """The fleet writer returns False on a failed write; the door raises and logs no receipt.
        Mutant: the write_json return ignored -> a receipt line lands and nothing raises, red."""
        manifest, settings_path = _backup_world(tmp_path, {"env": {}})
        original = settings_path.read_bytes()
        written: list = []

        def _failed_write(path, _data) -> bool:
            written.append(path)
            return False

        monkeypatch.setattr(provider_wire.json_handler, "write_json", _failed_write)

        with pytest.raises(SettingsBackupError) as refused:
            _wire(manifest, settings_path)

        receipts = _folder(settings_path) / "receipts.jsonl"
        lines = receipts.read_text(encoding="utf-8").splitlines() if receipts.exists() else []
        assert str(settings_path) in str(refused.value)
        assert lines == []
        assert settings_path.read_bytes() == original
        assert written == [settings_path]

    @pytest.mark.parametrize("door", ["setup-sh", "reconcile-stale-deny"])
    def test_each_other_writer_leaves_its_backup_and_receipt_under_its_door_name(
        self, tmp_path, monkeypatch, door
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        manifest, settings_path = _backup_world(tmp_path, {"permissions": {"deny": ["Bash(rm -rf*)", "Bash(keep*)"]}})
        original = settings_path.read_bytes()

        detail = ""
        if door == "setup-sh":
            refresh_provider_hooks(manifest, settings_path=settings_path)
        else:
            ((_label, _glyph, detail, _remedy),) = reconcile_stale_deny(fix=True)

        name = f"settings.json.{_STAMP}.{door}"
        assert _backups(settings_path) == [name]
        assert (_folder(settings_path) / name).read_bytes() == original
        (receipt,) = _receipts(settings_path)
        assert receipt["door"] == door
        assert receipt["before_sha256"] == _sha(original)
        assert receipt["after_sha256"] == _sha(settings_path.read_bytes()) != _sha(original)
        if door == "reconcile-stale-deny":
            assert receipt["summary"][0] == "Removed stale deny rules: Bash(rm -rf*)"
            assert str(_folder(settings_path) / name) in detail
            assert str(_folder(settings_path) / "receipts.jsonl") in detail

    def test_the_receipt_names_the_branch_the_cwd_sits_in_else_the_cwd_path(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        home = tmp_path / "home"
        branch = home / "src" / "scout"
        (branch / ".trinity").mkdir(parents=True)
        (branch / "apps").mkdir()
        (home / "TEST_REGISTRY.json").write_text("{}", encoding="utf-8")
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "scout"}}), encoding="utf-8"
        )
        outside = tmp_path / "outside"
        outside.mkdir()
        manifest, settings_path = _backup_world(tmp_path, {"env": {}})

        monkeypatch.chdir(branch / "apps")
        _wire(manifest, settings_path)
        monkeypatch.chdir(outside)
        _wire(manifest, settings_path)

        assert [r["actor"] for r in _receipts(settings_path)] == ["scout", str(outside)]

    @pytest.mark.parametrize("door", ["doctor", "setup-sh"])
    def test_an_unparseable_settings_file_refuses_and_stays_byte_identical(self, tmp_path, door) -> None:
        manifest, settings_path = _backup_world(tmp_path, None)
        settings_path.write_text('{"env": {},}', encoding="utf-8")
        original = settings_path.read_bytes()

        with pytest.raises(SettingsBackupError, match="unreadable"):
            if door == "doctor":
                plan_wire_provider(manifest, settings_path)
            else:
                refresh_provider_hooks(manifest, settings_path=settings_path)

        assert settings_path.read_bytes() == original

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
    def test_a_symlinked_settings_file_stays_a_symlink_after_the_wire(self, tmp_path) -> None:
        manifest, real = _backup_world(tmp_path, {"env": {}})
        link = tmp_path / "link" / "settings.json"
        link.parent.mkdir()
        link.symlink_to(real)

        _wire(manifest, link)

        assert link.is_symlink()
        assert json.loads(real.read_text(encoding="utf-8"))["includeGitInstructions"] is False

    def test_a_settings_file_changed_after_the_plan_refuses_the_write(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, {"env": {}})
        plan = plan_wire_provider(manifest, settings_path)
        assert plan is not None
        settings_path.write_text(json.dumps({"env": {"MINE": "1"}}), encoding="utf-8")
        edited = settings_path.read_bytes()

        with pytest.raises(SettingsBackupError, match="changed since planned"):
            apply_settings_plan(plan)

        assert settings_path.read_bytes() == edited


# =============================================================================
# TestInstallDoorEnvAndPermissions — setup.sh's second heredoc folded in (FPLAN-0645)
# =============================================================================


class TestInstallDoorEnvAndPermissions:
    """refresh_provider_hooks merges manifest env and permissions too, through auto_wire's helpers."""

    @pytest.fixture(autouse=True)
    def _not_msys(self, monkeypatch) -> None:
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("OSTYPE", raising=False)

    _EXTRA = {
        "env": {"AIPASS_HOME": "{{REPO_ROOT}}", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
        "permissions": {"deny": ["Bash(git push*)", "Read(~/.secrets/**)"], "ask": ["Edit(~/.claude/**)"]},
    }

    def test_the_install_door_lands_env_deny_and_ask_with_one_backup_and_one_receipt(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, {"env": {}}, self._EXTRA)

        refresh_provider_hooks(manifest, settings_path=settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["env"]["AIPASS_HOME"] == str(manifest.parent.parent)
        assert updated["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert updated["permissions"]["deny"] == ["Bash(git push*)", "Read(~/.secrets/**)"]
        assert updated["permissions"]["ask"] == ["Edit(~/.claude/**)"]
        (backup,) = _backups(settings_path)
        assert backup.endswith(".setup-sh")
        (receipt,) = _receipts(settings_path)
        assert receipt["door"] == "setup-sh"
        assert "Added deny rule: Bash(git push*)" in receipt["summary"]
        assert f"Set env AIPASS_HOME={manifest.parent.parent}" in receipt["summary"]

    def test_the_install_door_keeps_an_existing_env_value_and_never_duplicates_a_deny_rule(self, tmp_path) -> None:
        existing = {"env": {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}, "permissions": {"deny": ["Bash(git push*)"]}}
        manifest, settings_path = _backup_world(tmp_path, existing, self._EXTRA)

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        updated = json.loads(settings_path.read_text(encoding="utf-8"))
        assert updated["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "0"
        assert updated["permissions"]["deny"] == ["Bash(git push*)", "Read(~/.secrets/**)"]
        assert not [a for a in actions if "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in a or "Bash(git push*)" in a]

    @pytest.mark.parametrize(
        ("var", "value", "lands"),
        [("MSYSTEM", "MINGW64", True), ("MSYSTEM", "MSYS", True), ("OSTYPE", "msys", True), (None, None, False)],
        ids=["git-bash-mingw64", "msys", "ostype-msys", "not-msys"],
    )
    def test_pythonutf8_lands_only_under_an_msys_shell(self, tmp_path, monkeypatch, var, value, lands) -> None:
        if var:
            monkeypatch.setenv(var, value)
        manifest, settings_path = _backup_world(tmp_path, {"env": {}}, self._EXTRA)

        refresh_provider_hooks(manifest, settings_path=settings_path)

        env = json.loads(settings_path.read_text(encoding="utf-8"))["env"]
        assert ("PYTHONUTF8" in env) is lands
        if lands:
            assert env["PYTHONUTF8"] == "1"


# =============================================================================
# TestAipassHomeRepoint — install re-points AIPASS_HOME, doctor never does (FPLAN-0645)
# =============================================================================


class TestAipassHomeRepoint:
    """refresh_provider_hooks re-points exactly AIPASS_HOME; the doctor wire leaves it."""

    _EXTRA = {"env": {"AIPASS_HOME": "{{REPO_ROOT}}", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}}

    def _world(self, tmp_path, home: str):
        existing = {"env": {"AIPASS_HOME": home, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}}
        return _backup_world(tmp_path, existing, self._EXTRA)

    def test_the_install_door_re_points_a_different_home_and_keeps_every_other_env_key(self, tmp_path) -> None:
        old = str(tmp_path / "old_clone")
        manifest, settings_path = self._world(tmp_path, old)

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        new = str(manifest.parent.parent)
        env = json.loads(settings_path.read_text(encoding="utf-8"))["env"]
        assert env["AIPASS_HOME"] == new
        assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "0"
        assert f"Re-pointed AIPASS_HOME {old} -> {new}" in actions
        (receipt,) = _receipts(settings_path)
        assert f"Re-pointed AIPASS_HOME {old} -> {new}" in receipt["summary"]

    def test_doctor_fix_keeps_the_old_home_and_says_nothing_about_it(self, tmp_path) -> None:
        old = str(tmp_path / "old_clone")
        manifest, settings_path = self._world(tmp_path, old)

        actions = _wire(manifest, settings_path)

        assert json.loads(settings_path.read_text(encoding="utf-8"))["env"]["AIPASS_HOME"] == old
        assert not [a for a in actions if "AIPASS_HOME" in a]

    def test_a_home_that_already_matches_emits_no_line(self, tmp_path) -> None:
        manifest, settings_path = _backup_world(tmp_path, {}, self._EXTRA)
        settings_path.write_text(json.dumps({"env": {"AIPASS_HOME": str(manifest.parent.parent)}}), encoding="utf-8")

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        assert not [a for a in actions if "AIPASS_HOME" in a]


_CODEX = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/src/aipass/hooks/apps/handlers/bridges/codex.py"
_CODEX_ROWS = [
    {"command": f"{_CODEX} UserPromptSubmit:temporal", "event": "UserPromptSubmit", "timeout": 90},
    {"command": f"{_CODEX} PreToolUse", "event": "PreToolUse", "matcher": "Bash|apply_patch"},
    {"command": f"{_CODEX} Stop", "event": "Stop"},
]
_CODEX_FILE = {
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f"{_CODEX} UserPromptSubmit:temporal", "timeout": 90}]}
        ],
        "PreToolUse": [
            {"matcher": "Bash|apply_patch", "hooks": [{"type": "command", "command": f"{_CODEX} PreToolUse"}]}
        ],
        "Stop": [{"hooks": [{"type": "command", "command": f"{_CODEX} Stop"}]}],
    }
}


def _codex_world(tmp_path, rows: list, existing: dict | None = None):
    """A repo whose manifest carries cli.codex rows, a settings file outside it, and the user-level
    Codex hooks file in conftest's CODEX_HOME; returns manifest, settings, codex."""
    manifest = tmp_path / "repo" / ".claude" / "provider_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"cli": {"claude": {"hooks": []}, "codex": {"hooks": rows}}}), encoding="utf-8")
    settings_path = tmp_path / "home" / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    codex = tmp_path / "codex_home" / "hooks.json"
    if existing is not None:
        codex.parent.mkdir()
        codex.write_text(json.dumps(existing), encoding="utf-8")
    return manifest, settings_path, codex


class TestCodexHooks:
    """cli.codex rows merge into the user-level $CODEX_HOME/hooks.json, in Claude's hook shape, AIPass first."""

    def test_the_claude_door_leaves_codex_to_its_own_door(self, tmp_path) -> None:
        manifest, settings_path, codex = _codex_world(tmp_path, _CODEX_ROWS)

        actions = refresh_provider_hooks(manifest, settings_path=settings_path)

        assert not codex.parent.exists()
        assert not [a for a in actions if "Codex" in a]

    def test_the_install_door_writes_the_codex_file_in_claude_shape_with_its_receipt(self, tmp_path) -> None:
        manifest, _settings, codex = _codex_world(tmp_path, _CODEX_ROWS)

        actions = refresh_codex(manifest)

        assert json.loads(codex.read_text(encoding="utf-8")) == _CODEX_FILE
        assert "Wrote 3 Codex hook(s) from cli.codex" in actions
        assert actions[-1] == f"Codex hooks: 3 AIPass row(s) in {codex}"
        receipt = next(r for r in _receipts(codex) if r["file"] == "hooks.json")
        assert receipt["door"] == settings_backup.DOOR_SETUP_SH
        assert receipt["after_sha256"] == hashlib.sha256(codex.read_bytes()).hexdigest()
        assert not (tmp_path / "repo" / ".codex").exists()

    def test_the_users_rows_are_kept_behind_the_aipass_groups_after_a_backup(self, tmp_path) -> None:
        """Mutant: putting foreign groups first shifts every AIPass trust key and goes red."""
        mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
        stale = {"hooks": [{"type": "command", "command": f"{_CODEX} Old"}, {"type": "command", "command": "echo too"}]}
        users = {"hooks": {"Stop": [mine, stale], "SessionEnd": [mine]}, "extra": 1}
        manifest, _settings, codex = _codex_world(tmp_path, _CODEX_ROWS, users)
        original = codex.read_text(encoding="utf-8")

        plan = plan_codex_hooks(manifest)
        assert plan is not None
        apply_settings_plan(plan)

        written = json.loads(codex.read_text(encoding="utf-8"))
        too = {"hooks": [{"type": "command", "command": "echo too"}]}
        assert written == {
            "hooks": {**_CODEX_FILE["hooks"], "Stop": [*_CODEX_FILE["hooks"]["Stop"], mine, too], "SessionEnd": [mine]},
            "extra": 1,
        }
        (backup,) = _backups(codex)
        assert (_folder(codex) / backup).read_text(encoding="utf-8") == original
        assert plan_codex_hooks(manifest) is None

    def test_the_trust_keys_are_the_user_file_snake_event_group_and_index(self, tmp_path) -> None:
        path = tmp_path / "codex_home" / "hooks.json"

        assert codex_trust_keys(path, _CODEX_FILE) == [
            f"{path}:user_prompt_submit:0:0",
            f"{path}:pre_tool_use:0:0",
            f"{path}:stop:0:0",
        ]

    def test_a_matching_file_plans_nothing(self, tmp_path) -> None:
        manifest, _settings, _codex = _codex_world(tmp_path, _CODEX_ROWS, _CODEX_FILE)

        assert plan_codex_hooks(manifest) is None

    def test_no_codex_rows_never_empties_the_codex_file(self, tmp_path) -> None:
        manifest, settings_path, codex = _codex_world(tmp_path, [], _CODEX_FILE)
        original = codex.read_text(encoding="utf-8")

        actions = refresh_codex(manifest)

        assert plan_codex_hooks(manifest) is None
        assert codex.read_text(encoding="utf-8") == original
        assert not [a for a in actions if "hook(s)" in a]
        assert [r["file"] for r in _receipts(codex)] == ["config.toml"]


@pytest.mark.usefixtures("codex_on_path")
class TestCodexDoctorRows:
    """Doctor's codex hooks rows: the user-level file, its trust in config.toml, a repo file firing twice."""

    def _config(self, tmp_path, keys: list) -> None:
        tables = "".join(f'[hooks.state."{k}"]\ntrusted_hash = "sha256:x"\n' for k in keys)
        (tmp_path / "codex_home" / "config.toml").write_text(tables, encoding="utf-8")

    def _rows(self, manifest) -> list:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        return [(r.label, r.glyph, r.detail, r.remediation) for r in check_codex_hooks(doc, manifest)]

    def test_a_current_and_trusted_user_file_passes_both_rows(self, tmp_path) -> None:
        manifest, _settings, codex = _codex_world(tmp_path, _CODEX_ROWS, _CODEX_FILE)
        self._config(tmp_path, codex_trust_keys(codex, _CODEX_FILE))

        assert self._rows(manifest) == [
            ("codex hooks", GLYPH_PASS, "3 Codex hooks match cli.codex", ""),
            ("codex trust", GLYPH_PASS, "3 AIPass rows trusted", ""),
        ]

    def test_one_untrusted_row_warns_with_the_trust_step(self, tmp_path) -> None:
        manifest, _settings, codex = _codex_world(tmp_path, _CODEX_ROWS, _CODEX_FILE)
        self._config(tmp_path, codex_trust_keys(codex, _CODEX_FILE)[1:])

        trust = (
            "codex trust",
            GLYPH_WARN,
            "Codex hooks not trusted (1 of 3 rows)",
            "Run `codex` once and choose 'Trust all and continue'",
        )
        assert self._rows(manifest)[1] == trust

    def test_bridge_rows_in_the_repo_file_fail_and_fix_leaves_that_file(self, tmp_path) -> None:
        """Mutant: dropping the double-fire check loses the FAIL row and goes red."""
        manifest, _settings, codex = _codex_world(tmp_path, _CODEX_ROWS)
        repo = tmp_path / "repo" / ".codex" / "hooks.json"
        repo.parent.mkdir()
        repo.write_text(json.dumps(_CODEX_FILE), encoding="utf-8")
        original = repo.read_bytes()

        rows = self._rows(manifest)
        plan = plan_codex_hooks(manifest)
        assert plan is not None
        apply_settings_plan(plan)

        detail = f"Codex hooks double-fire: {repo} still holds bridge rows"
        assert rows[-1] == (
            "codex double-fire",
            GLYPH_FAIL,
            detail,
            "Remove them by hand: --fix leaves the project's file",
        )
        assert repo.read_bytes() == original
        assert json.loads(codex.read_text(encoding="utf-8")) == _CODEX_FILE

    def test_a_repo_file_with_only_its_own_rows_is_no_double_fire(self, tmp_path) -> None:
        manifest, _settings, _codex = _codex_world(tmp_path, _CODEX_ROWS)
        repo = tmp_path / "repo" / ".codex" / "hooks.json"
        repo.parent.mkdir()
        repo.write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}),
            encoding="utf-8",
        )

        assert [r[0] for r in self._rows(manifest)] == ["codex hooks"]


_PINS_TOML = """include_collaboration_mode_instructions = false
[features]
collaboration_modes = false
memories = false

[tools.experimental_request_user_input]
enabled = false
"""


class TestCodexPins:
    """setup.sh sets the four Codex config pins line by line, keeping every other line of config.toml."""

    def test_a_missing_config_gets_the_four_pins_and_nothing_else(self, tmp_path) -> None:
        config = tmp_path / "codex_home" / "config.toml"
        config.parent.mkdir()

        actions = set_codex_pins(config)

        assert config.read_text(encoding="utf-8") == _PINS_TOML
        assert actions[0] == (
            f"Set Codex pins in {config}: features.memories, include_collaboration_mode_instructions,"
            " features.collaboration_modes, tools.experimental_request_user_input.enabled"
        )

    def test_the_owners_lines_stay_and_only_the_wrong_pin_lines_change(self, tmp_path) -> None:
        """Mutant: inserting a table pin at the end of the file, not under its header, goes red."""
        config = tmp_path / "config.toml"
        owner = (
            'model = "gpt-6.1-sol"  # mine\n'
            "\n"
            "[features]\n"
            "hooks = true\n"
            "memories = true\n"
            "\n"
            '[projects."/x"]\n'
            'trust_level = "trusted"\n'
        )
        config.write_text(owner, encoding="utf-8")

        set_codex_pins(config)

        assert config.read_text(encoding="utf-8") == (
            'model = "gpt-6.1-sol"  # mine\n'
            "\n"
            "include_collaboration_mode_instructions = false\n"
            "[features]\n"
            "collaboration_modes = false\n"
            "hooks = true\n"
            "memories = false\n"
            "\n"
            '[projects."/x"]\n'
            'trust_level = "trusted"\n'
            "\n"
            "[tools.experimental_request_user_input]\n"
            "enabled = false\n"
        )
        (backup,) = _backups(config)
        assert (_folder(config) / backup).read_text(encoding="utf-8") == owner

    def test_set_pins_write_nothing(self, tmp_path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(_PINS_TOML, encoding="utf-8")

        assert set_codex_pins(config) == []
        assert not _folder(config).exists()

    @pytest.mark.parametrize(
        "text", ["features.memories = true\n", "[features\n", '[features]\nnote = """\nmemories = x\n"""\n']
    )
    def test_a_config_it_cannot_edit_line_by_line_is_refused_untouched(self, tmp_path, text) -> None:
        """A dotted pin collides with the [features] header the edit adds; a broken file is not parsed at all;
        a pin-shaped line inside a string would be edited while the pin stays unset.
        Mutant: dropping the after-edit pin check writes the third and goes red."""
        config = tmp_path / "config.toml"
        config.write_text(text, encoding="utf-8")

        with pytest.raises(SettingsBackupError, match="not touching it"):
            set_codex_pins(config)

        assert config.read_text(encoding="utf-8") == text
        assert not _folder(config).exists()


_OPENCODE = "$AIPASS_HOME/.venv/bin/python3 $AIPASS_HOME/src/aipass/hooks/apps/handlers/bridges/opencode.py"
_PLUGIN_SOURCE = b"// the hooks branch's plugin\nexport default {}\n"


def _opencode_world(tmp_path, rows: bool = True, installed: bytes | None = None):
    """A repo with the plugin source and cli.opencode rows, a scratch home, and conftest's XDG_CONFIG_HOME;
    returns manifest, source, the plugin path."""
    repo = tmp_path / "repo"
    manifest = repo / ".claude" / "provider_manifest.json"
    manifest.parent.mkdir(parents=True)
    opencode = {"hooks": [{"command": f"{_OPENCODE} Stop", "event": "Stop"}] if rows else []}
    manifest.write_text(json.dumps({"cli": {"claude": {"hooks": []}, "opencode": opencode}}), encoding="utf-8")
    source = repo / "src" / "aipass" / "hooks" / "apps" / "handlers" / "bridges" / "opencode_plugin.ts"
    source.parent.mkdir(parents=True)
    source.write_bytes(_PLUGIN_SOURCE)
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    plugin = tmp_path / "xdg_config" / "opencode" / "plugins" / "aipass.ts"
    if installed is not None:
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(installed)
    return manifest, source, plugin


class TestOpenCodePlugin:
    """The plugin copied byte-equal into $XDG_CONFIG_HOME/opencode/plugins, backup and receipt first."""

    def test_the_install_door_copies_the_plugin_byte_equal_with_its_receipt_once(self, tmp_path) -> None:
        manifest, _source, plugin = _opencode_world(tmp_path)

        actions = install_opencode_plugin(manifest)
        again = install_opencode_plugin(manifest)

        assert plugin.read_bytes() == _PLUGIN_SOURCE
        assert actions[0] == f"Installed the OpenCode plugin at {plugin}"
        (receipt,) = _receipts(plugin)
        assert (receipt["file"], receipt["door"]) == ("aipass.ts", "setup-sh")
        assert receipt["after_sha256"] == _sha(_PLUGIN_SOURCE)
        assert again == []

    def test_a_stale_plugin_is_backed_up_then_replaced(self, tmp_path) -> None:
        manifest, _source, plugin = _opencode_world(tmp_path, installed=b"// old\n")

        actions = install_opencode_plugin(manifest, settings_backup.DOOR_DOCTOR_FIX)

        (backup,) = _backups(plugin)
        assert (_folder(plugin) / backup).read_bytes() == b"// old\n"
        assert actions[0] == f"Backed up the OpenCode plugin to {_folder(plugin) / backup}"
        assert plugin.read_bytes() == _PLUGIN_SOURCE

    @pytest.mark.usefixtures("opencode_on_path")
    def test_a_manifest_without_opencode_rows_installs_nothing(self, tmp_path) -> None:
        manifest, _source, plugin = _opencode_world(tmp_path, rows=False)

        assert install_opencode_plugin(manifest) == []
        assert check_opencode_side(manifest) == []
        assert not plugin.parent.exists()


@pytest.mark.usefixtures("opencode_on_path")
class TestOpenCodeDoctorRows:
    """Doctor's opencode rows: the plugin measured against the source, fixed by --fix; the CLI read, never run."""

    def test_a_missing_plugin_warns_with_the_cp_cure_and_fix_yes_installs_it_until_it_passes(self, tmp_path) -> None:
        manifest, source, plugin = _opencode_world(tmp_path)

        before = check_opencode_side(manifest)
        with _home_at(tmp_path / "home"):
            fixed = fix_provider_settings(manifest, yes=True)
        after = check_opencode_side(manifest)

        cure = f"Run: aipass doctor --fix (or cp {source} {plugin})"
        assert before[0] == ("opencode plugin", GLYPH_WARN, f"OpenCode plugin missing: {plugin}", cure)
        assert before[1][:2] == ("opencode binary", GLYPH_WARN)
        assert fixed == []
        assert plugin.read_bytes() == _PLUGIN_SOURCE
        assert after[0] == ("opencode plugin", GLYPH_PASS, f"{plugin} matches the hooks branch copy", "")

    def test_a_stale_plugin_warns_and_the_json_plan_names_the_copy_without_writing(self, tmp_path) -> None:
        manifest, source, plugin = _opencode_world(tmp_path, installed=b"// old\n")

        row, *_cli_rows = check_opencode_side(manifest)
        with _home_at(tmp_path / "home"):
            report = settings_fix_report(manifest)

        assert row.detail == f"OpenCode plugin stale (differs from the hooks branch copy): {plugin}"
        assert report["planned"] == [f"Install the OpenCode plugin: cp {source} {plugin}"]
        assert report["applied"] is False
        assert plugin.read_bytes() == b"// old\n"

    def test_doctor_shows_the_opencode_rows_after_the_codex_ones(self, tmp_path) -> None:
        manifest, _source, _plugin = _opencode_world(tmp_path)

        with patch("aipass.aipass.apps.modules.doctor._find_manifest", return_value=manifest):
            with _home_at(tmp_path / "home"):
                labels = [r.label for r in check_provider_manifest() if r.label.startswith("opencode")]

        assert labels == ["opencode plugin", "opencode binary", "opencode login", "opencode model"]

    def test_no_opencode_installed_shows_no_row_plans_nothing_and_writes_no_plugin(self, tmp_path, monkeypatch) -> None:
        """setup.sh's `command -v opencode` rule: no binary, no plugin row, plan or write."""
        manifest, _source, plugin = _opencode_world(tmp_path)
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        doc["cli"]["claude"]["permissions"] = {"deny": ["Edit(~/x)"]}  # another plan, so --fix does write
        manifest.write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setattr(opencode_cli, "_which", lambda name, path=None: None)

        with _home_at(tmp_path / "home"):
            report = settings_fix_report(manifest)
            fixed = fix_provider_settings(manifest, yes=True)

        assert check_opencode_side(manifest) == []
        assert not [line for line in report["planned"] if "OpenCode" in line]
        assert fixed == []
        assert (tmp_path / "home" / ".claude" / "settings.json").exists()
        assert not plugin.parent.exists()

    def _cli(self, monkeypatch, tmp_path, auth: tuple = (0, "[]"), config: str | None = None) -> list:
        searched = []
        answers = {"--version": (0, "opencode v2.2.0\n"), "auth": auth}

        def which(name, path=None):
            searched.append(path)
            return "/fake/opencode"

        def run(args, **_kw):
            rc, out = answers[args[1]]
            return subprocess.CompletedProcess(args, rc, out, "")

        monkeypatch.setattr(opencode_cli, "_which", which)
        monkeypatch.setattr(opencode_cli, "_run", run)
        if config is not None:
            (tmp_path / "opencode.json").write_text(config, encoding="utf-8")
        rows = [tuple(r) for r in opencode_cli.check_opencode_cli(tmp_path)]
        assert searched[0].endswith(os.pathsep + str(Path.home() / ".opencode" / "bin"))
        return rows

    def test_a_signed_out_opencode_on_its_default_model_passes_every_row(self, monkeypatch, tmp_path) -> None:
        assert self._cli(monkeypatch, tmp_path) == [
            ("opencode binary", GLYPH_PASS, "opencode v2.2.0 (/fake/opencode)", ""),
            ("opencode login", GLYPH_PASS, "none (free models only)", ""),
            ("opencode model", GLYPH_PASS, "none set — OpenCode's default", ""),
        ]

    def test_a_signed_in_provider_and_a_configured_model_are_named(self, monkeypatch, tmp_path) -> None:
        rows = self._cli(monkeypatch, tmp_path, (0, '[{"provider": "anthropic"}]'), '{"model": "opencode/glm"}')

        assert rows[1] == ("opencode login", GLYPH_PASS, "anthropic", "")
        assert rows[2] == ("opencode model", GLYPH_PASS, f"opencode/glm (from {tmp_path / 'opencode.json'})", "")

    def test_a_failing_auth_list_and_a_broken_config_warn(self, monkeypatch, tmp_path) -> None:
        rows = self._cli(monkeypatch, tmp_path, (1, "auth broke\n"), "{not json")

        assert rows[1] == ("opencode login", GLYPH_WARN, "auth broke", "Run: opencode auth list")
        assert self._cli(monkeypatch, tmp_path, (1, "[]"))[1][1] == GLYPH_WARN
        assert rows[2][1] == GLYPH_WARN
        assert rows[2][2].startswith(f"{tmp_path / 'opencode.json'} unreadable")

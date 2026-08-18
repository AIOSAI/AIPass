# =================== AIPass ====================
# Name: test_host_settings.py
# Description: Host API settings handler — the desktop's gear rules, held in Python
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
The settings lane mirrors @baud's settings.rs, and these tests pin the rules
that make the two faces write one truth: surgical three-state patches, the
never-treat-unreadable-as-blank refusal, and the idempotent mute flag.
"""

import json
import os

import pytest

from aipass.api.apps.handlers.host import settings as host_settings


def agent_file(root):
    return root / ".claude" / "settings.local.json"


class TestAgentSettings:
    """The surgical door: three owned keys, everything else survives."""

    def test_a_fresh_branch_reads_all_null(self, tmp_path) -> None:
        """No settings file is not a fault — every dial sits at absent."""
        assert host_settings.read_agent_settings(tmp_path) == {
            "model": None,
            "auto_compact_enabled": None,
            "auto_compact_window": None,
        }

    def test_a_patch_sets_claudes_own_spelling_and_preserves_strangers(self, tmp_path) -> None:
        """camelCase on disk, snake_case in the API — and the operator's other
        keys come back byte-identical, which is the whole surgical promise."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}, "model": "opus"}))

        view = host_settings.write_agent_settings(tmp_path, {"model": "sonnet", "auto_compact_window": 350_000})

        document = json.loads(path.read_text())
        assert document["model"] == "sonnet"
        assert document["autoCompactWindow"] == 350_000
        assert document["permissions"] == {"allow": ["Bash"]}
        assert view["model"] == "sonnet"
        assert view["auto_compact_window"] == 350_000

    def test_null_removes_and_absent_touches_nothing(self, tmp_path) -> None:
        """The three-state contract in one write."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus", "autoCompactEnabled": True}))

        view = host_settings.write_agent_settings(tmp_path, {"model": None})

        document = json.loads(path.read_text())
        assert "model" not in document
        assert document["autoCompactEnabled"] is True
        assert view == {"model": None, "auto_compact_enabled": True, "auto_compact_window": None}

    def test_a_corrupt_file_refuses_both_directions_and_stays_corrupt(self, tmp_path) -> None:
        """Unreadable must never be treated as blank: a write that 'recovered'
        a corrupt file to {} would destroy whatever the operator had there."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")

        with pytest.raises(host_settings.SettingsRefused):
            host_settings.read_agent_settings(tmp_path)
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"model": "opus"})
        assert path.read_text() == "{not json"

    def test_wrong_typed_values_read_as_null(self, tmp_path) -> None:
        """A dial cannot show a value it does not understand — including the
        bool-is-an-int trap, which is why the window check excludes bools."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": 7, "autoCompactEnabled": "yes", "autoCompactWindow": True}))

        assert host_settings.read_agent_settings(tmp_path) == {
            "model": None,
            "auto_compact_enabled": None,
            "auto_compact_window": None,
        }

    def test_the_allowlist_is_the_contract(self, tmp_path) -> None:
        """Unknown fields refuse — the door owns three keys and no more."""
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"permissions": {}})
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"auto_compact_window": True})
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"auto_compact_window": -5})
        assert not agent_file(tmp_path).exists()


class TestBaudSettings:
    """The opaque document: shallow merge, null removes, nested replaces."""

    def test_merge_keeps_null_removes_and_replaces_subtrees(self, tmp_path) -> None:
        path = tmp_path / ".aipass" / "baud.settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"startup_agent": "devpulse", "poll_interval_ms": 5000, "extra": {"a": 1}}))

        result = host_settings.write_baud_settings(
            tmp_path, {"startup_agent": None, "bell_sound": True, "extra": {"b": 2}}
        )

        assert "startup_agent" not in result
        assert result["poll_interval_ms"] == 5000
        assert result["bell_sound"] is True
        # Replaced whole, never merged into — a caller says what a subtree IS.
        assert result["extra"] == {"b": 2}
        assert json.loads(path.read_text()) == result


class TestHooksSound:
    """The mute flag: a file, inverted on purpose, idempotent both ways."""

    def test_active_means_no_flag_and_flips_are_idempotent(self, tmp_path) -> None:
        flag = tmp_path / "aipass-hooks-muted"

        assert host_settings.hooks_sound_get(flag) is True
        assert host_settings.hooks_sound_set(False, flag) is False
        assert host_settings.hooks_sound_set(False, flag) is False
        assert flag.exists()
        assert host_settings.hooks_sound_set(True, flag) is True
        assert host_settings.hooks_sound_set(True, flag) is True
        assert not flag.exists()


class TestAnUnreadableFileIsNeverBlank:
    """
    The module docstring's own rule, now held all the way down.

    read_object used to answer {} for EVERY OSError. Two very different
    situations were arriving at the same answer: a branch that has no settings
    yet, and a settings file this process is not allowed to read. The first is
    ordinary; the second is a fault, and reading it as blank invites a patch to
    write a fresh document over settings that were only ever unreadable.
    """

    def test_a_branch_with_no_settings_still_reads_as_blank(self, tmp_path) -> None:
        """The no-fault case, unchanged: absent means absent."""
        assert host_settings.read_object(tmp_path / "settings.local.json") == {}

    def test_a_missing_parent_directory_also_reads_as_blank(self, tmp_path) -> None:
        """Nothing on the way to the file exists either — still just absent."""
        assert host_settings.read_object(tmp_path / "nope" / "settings.local.json") == {}

    def test_a_directory_where_the_file_should_be_is_a_fault(self, tmp_path) -> None:
        """Something IS there and it cannot be read as settings. Say so."""
        occupied = tmp_path / "settings.local.json"
        occupied.mkdir()

        with pytest.raises(host_settings.SettingsUnavailable) as refusal:
            host_settings.read_object(occupied)

        assert "settings.local.json" in str(refusal.value)

    @pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything; the mode says nothing to it")
    def test_a_file_we_may_not_read_is_a_fault_not_a_blank(self, tmp_path) -> None:
        """The one that would have cost real settings: unreadable, not empty."""
        secret = tmp_path / "settings.local.json"
        secret.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        secret.chmod(0o000)

        try:
            with pytest.raises(host_settings.SettingsUnavailable):
                host_settings.read_object(secret)
        finally:
            secret.chmod(0o600)


class TestAFailedWriteLeavesNothingBehind:
    """The staged file is cleanup, and cleanup that fails is still reported."""

    def test_the_staged_file_does_not_survive_a_failed_write(self, tmp_path) -> None:
        path = tmp_path / "settings.local.json"

        with pytest.raises(TypeError):
            host_settings.write_atomically(path, {"unserialisable": object()})

        assert not path.exists()
        assert list(tmp_path.iterdir()) == []

    def test_a_cleanup_that_itself_fails_is_logged_not_swallowed(self, tmp_path, monkeypatch) -> None:
        """
        Losing the temp file is survivable; losing the FACT is not. The original
        failure still travels — cleanup never overwrites the reason.
        """
        path = tmp_path / "settings.local.json"
        complaints = []

        def refuse_to_unlink(_target):
            raise OSError("the staged file cannot be removed either")

        monkeypatch.setattr(host_settings.os, "unlink", refuse_to_unlink)
        monkeypatch.setattr(
            host_settings.logger, "warning", lambda *a, **k: complaints.append(a[0] % a[1:] if len(a) > 1 else a[0])
        )

        with pytest.raises(TypeError):
            host_settings.write_atomically(path, {"unserialisable": object()})

        assert complaints, "a failed cleanup left no trace at all"
        assert any("staged" in line for line in complaints)

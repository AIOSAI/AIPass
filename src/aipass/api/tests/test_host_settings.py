# =================== AIPass ====================
# Name: test_host_settings.py
# Description: Host API settings handler — the desktop's gear rules, held in Python
# Version: 1.2.0
# Created: 2026-08-16
# Modified: 2026-11-01
# =============================================

"""Tests for apps/handlers/host/settings.py, the desktop's settings lane."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — @baud's settings.rs, the other face; @baud's own tests
# seedgo: no-test-needed(covered_elsewhere) — the flag path HOOKS_SOUND_STATE's child reads; @hooks' tests of sound.py

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.api.apps.handlers.host import settings as host_settings

WHERE_THE_FLAG_LIVES = "from aipass.hooks.apps import sound; print(sound.SOUND_FLAG)"


def _where_the_door_would_write() -> Path:
    """
    Ask @hooks' own module, in a child that inherits this process's environment.

    Never compute it here: the module's own path is the one the door's process will touch."""
    child = subprocess.run(
        [sys.executable, "-c", WHERE_THE_FLAG_LIVES],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=host_settings.HOOKS_SOUND_TIMEOUT_SECONDS,
    )

    assert child.returncode == 0, child.stderr
    return Path(child.stdout.strip())


def _fingerprint(path: Path) -> tuple:
    """Enough of a file to notice it was touched at all."""
    if not path.exists():
        return (False, None, None)

    stat = path.stat()
    return (True, stat.st_size, stat.st_mtime_ns)


def _ok() -> subprocess.CompletedProcess:
    """What the door returns when it is happy — and, as it turns out, also when
    it has no idea what you asked for. See the test that pins that."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


@pytest.fixture
def sound_elsewhere(tmp_path, monkeypatch):
    """
    @hooks' flag, relocated into this test's own directory, plus a stand-in for
    the door that moves it."""
    flag = tmp_path / ".aipass" / "aipass-hooks-sound-on"
    calls: list = []

    def fake_door(command, **kwargs):
        calls.append(list(command))
        if command == host_settings.HOOKS_SOUND_STATE:
            state = "active" if flag.exists() else "muted"
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=f"{state}\n", stderr="")
        verb = command[-1]
        if verb == "on":
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()
        elif verb == "off":
            flag.unlink(missing_ok=True)
        return _ok()

    monkeypatch.setattr(host_settings.subprocess, "run", fake_door)
    return flag, calls


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
        path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}, "model": "opus"}), encoding="utf-8")

        view = host_settings.write_agent_settings(tmp_path, {"model": "sonnet", "auto_compact_window": 350_000})

        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["model"] == "sonnet"
        assert document["autoCompactWindow"] == 350_000
        assert document["permissions"] == {"allow": ["Bash"]}
        assert view["model"] == "sonnet"
        assert view["auto_compact_window"] == 350_000

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits; Windows has none to keep")
    def test_a_write_keeps_the_files_mode(self, tmp_path) -> None:
        """The staged file is born 0600; the replaced file must keep the mode it had."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        path.chmod(0o664)

        host_settings.write_agent_settings(tmp_path, {"auto_compact_window": 300_000})

        assert path.stat().st_mode & 0o777 == 0o664

    def test_null_removes_and_absent_touches_nothing(self, tmp_path) -> None:
        """The three-state contract in one write."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus", "autoCompactEnabled": True}), encoding="utf-8")

        view = host_settings.write_agent_settings(tmp_path, {"model": None})

        document = json.loads(path.read_text(encoding="utf-8"))
        assert "model" not in document
        assert document["autoCompactEnabled"] is True
        assert view == {"model": None, "auto_compact_enabled": True, "auto_compact_window": None}

    def test_a_corrupt_file_refuses_both_directions_and_stays_corrupt(self, tmp_path) -> None:
        """Unreadable must never be treated as blank: a write that 'recovered'
        a corrupt file to {} would destroy whatever the operator had there."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(host_settings.SettingsRefused):
            host_settings.read_agent_settings(tmp_path)
        with pytest.raises(host_settings.SettingsRefused):
            host_settings.write_agent_settings(tmp_path, {"model": "opus"})
        assert path.read_text(encoding="utf-8") == "{not json"

    def test_wrong_typed_values_read_as_null(self, tmp_path) -> None:
        """A dial cannot show a value it does not understand — including the
        bool-is-an-int trap, which is why the window check excludes bools."""
        path = agent_file(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"model": 7, "autoCompactEnabled": "yes", "autoCompactWindow": True}), encoding="utf-8"
        )

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
        path.write_text(
            json.dumps({"startup_agent": "devpulse", "poll_interval_ms": 5000, "extra": {"a": 1}}), encoding="utf-8"
        )

        result = host_settings.write_baud_settings(
            tmp_path, {"startup_agent": None, "bell_sound": True, "extra": {"b": 2}}
        )

        assert "startup_agent" not in result
        assert result["poll_interval_ms"] == 5000
        assert result["bell_sound"] is True
        assert result["extra"] == {"b": 2}
        assert json.loads(path.read_text(encoding="utf-8")) == result


class TestHooksSound:
    """The mute flag: @hooks' file, @hooks' door, idempotent both ways."""

    def test_this_module_does_not_know_where_the_mute_flag_lives(self) -> None:
        """The boundary, stated as a fact about this file's source."""
        source = Path(host_settings.__file__).read_text(encoding="utf-8")

        assert "aipass-hooks-muted" not in source
        assert "aipass-hooks-sound-on" not in source
        assert "hooks_mute_flag" not in source

    def test_no_hooks_code_is_held_in_process(self) -> None:
        """A long-running server would keep the @hooks code it started with; every read is a fresh child."""
        assert not hasattr(host_settings, "hooks_sound")
        assert host_settings.HOOKS_SOUND_STATE[0] == sys.executable

    def test_the_flip_goes_through_the_hooks_door(self, sound_elsewhere) -> None:
        """The WRITE is the registered command, not a touch and an unlink."""
        flag, calls = sound_elsewhere

        host_settings.hooks_sound_set(True)
        host_settings.hooks_sound_set(False)

        flips = [call for call in calls if call != host_settings.HOOKS_SOUND_STATE]
        assert flips == [["drone", "@hooks", "hooksound", "on"], ["drone", "@hooks", "hooksound", "off"]]

    def test_off_by_default_active_means_the_on_flag_and_flips_are_idempotent(self, sound_elsewhere) -> None:
        flag, _ = sound_elsewhere

        assert host_settings.hooks_sound_get() is False
        assert host_settings.hooks_sound_set(True) is True
        assert host_settings.hooks_sound_set(True) is True
        assert flag.exists()
        assert host_settings.hooks_sound_set(False) is False
        assert host_settings.hooks_sound_set(False) is False
        assert not flag.exists()

    @pytest.mark.parametrize("answer", [_ok(), subprocess.CompletedProcess([], 1, "active\n", "Traceback: no hooks")])
    def test_a_state_read_that_says_nothing_known_is_a_refusal_not_a_guess(self, answer) -> None:
        with patch.object(host_settings.subprocess, "run", return_value=answer):
            with pytest.raises(host_settings.SettingsUnavailable) as refusal:
                host_settings.hooks_sound_get()

        assert "hooks sound state could not be read" in str(refusal.value)

    def test_a_door_that_answers_but_does_not_flip_is_a_failure(self, sound_elsewhere) -> None:
        """
        MEASURED, and the reason this lane re-reads instead of trusting a zero.

        An unknown hooksound verb exits ZERO too; the flag is the only witness."""
        flag, _ = sound_elsewhere
        honest = host_settings.subprocess.run

        def deaf(command, **kwargs):
            return honest(command, **kwargs) if command == host_settings.HOOKS_SOUND_STATE else _ok()

        with patch.object(host_settings.subprocess, "run", deaf):
            with pytest.raises(host_settings.SettingsUnavailable) as refusal:
                host_settings.hooks_sound_set(True)

        assert "hook sounds are still off" in str(refusal.value)
        assert not flag.exists()

    def test_a_door_that_cannot_be_reached_refuses_rather_than_writing_the_file(self, sound_elsewhere) -> None:
        """
        No silent fallback to hand-writing. If the door is gone, say so — the
        one thing this lane must never do is quietly become the thing it replaced."""
        flag, _ = sound_elsewhere

        with patch.object(host_settings.subprocess, "run", side_effect=FileNotFoundError("drone")):
            with pytest.raises(host_settings.SettingsUnavailable):
                host_settings.hooks_sound_set(True)

        assert not flag.exists()

    def test_the_door_really_answers_to_this_command(self, tmp_path, monkeypatch) -> None:
        """
        NOT hermetic, on purpose, and the only test here that is not.

        The mocks pin what the lane sends, not that @hooks still answers the verb.
        It skips without a live @hooks (CI: a tmp registry cannot point at the real tree)."""
        operator_flag = _where_the_door_would_write()
        before = _fingerprint(operator_flag)

        flag = tmp_path / ".aipass" / operator_flag.name
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        # TMPDIR too: the door moves a legacy temp-dir flag once, and the operator's must never be the one moved.
        monkeypatch.setenv("TMPDIR", str(tmp_path))

        listening = subprocess.run(
            list(host_settings.HOOKS_SOUND_DOOR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=host_settings.HOOKS_SOUND_TIMEOUT_SECONDS,
        )
        if listening.returncode != 0:
            pytest.skip(
                "no live @hooks on this machine — the door said: "
                f"{(listening.stderr or listening.stdout).strip()[:120]}"
            )

        would_write = _where_the_door_would_write()
        assert would_write == flag, (
            "the redirect did not reach the door's own process — refusing to "
            f"flip anything. It would have written {would_write}"
        )

        try:
            assert host_settings.hooks_sound_set(True) is True
            assert flag.exists()
            assert host_settings.hooks_sound_set(False) is False
            assert not flag.exists()
        finally:
            assert _fingerprint(operator_flag) == before


class TestTheGuardsOnTheLiveDoorTest:
    """Two hermetic tests about the ONE non-hermetic test above it."""

    def test_the_redirect_check_asks_the_door_rather_than_computing_the_answer(self, tmp_path, monkeypatch) -> None:
        """A HOME the child inherits is the HOME the door's own module resolves against."""
        operator_flag = _where_the_door_would_write()
        elsewhere = tmp_path / "elsewhere"
        monkeypatch.setenv("HOME", str(elsewhere))
        monkeypatch.setenv("USERPROFILE", str(elsewhere))

        would_write = _where_the_door_would_write()

        assert elsewhere in would_write.parents
        assert would_write != operator_flag

    def test_the_fingerprint_notices_a_rewrite_that_changed_nothing(self, tmp_path) -> None:
        """Why the operator's flag is fingerprinted with its mtime and not just its state."""
        flag = tmp_path / "aipass-hooks-muted"
        flag.touch()
        before = _fingerprint(flag)

        flag.touch()
        os.utime(flag, ns=(before[2] + 1_000_000_000, before[2] + 1_000_000_000))

        assert flag.exists()
        assert _fingerprint(flag) != before


class TestAnUnreadableFileIsNeverBlank:
    """The module docstring's own rule, now held all the way down."""

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

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="chmod 0o000 cannot construct an unreadable file here - no POSIX mode bits",
    )
    # Trap: these evaluate at collection. test_windows_import hides os.geteuid with
    # os.name still "posix", so a bare os.geteuid() takes the whole file down; keep the getattr.
    @pytest.mark.skipif(
        sys.platform == "win32" or getattr(os, "geteuid", lambda: -1)() == 0,
        reason="a file mode only means something to a non-root POSIX process",
    )
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
        failure still travels — cleanup never overwrites the reason."""
        path = tmp_path / "settings.local.json"
        complaints = []

        def refuse_to_unlink(_target):
            raise OSError("the staged file cannot be removed either")

        monkeypatch.setattr(host_settings.os, "unlink", refuse_to_unlink)
        monkeypatch.setattr(
            host_settings.logger,
            "warning",
            lambda *a, **k: complaints.append(a[0] % a[1:] if len(a) > 1 else a[0] if a else ""),
        )

        with pytest.raises(TypeError):
            host_settings.write_atomically(path, {"unserialisable": object()})

        assert complaints, "a failed cleanup left no trace at all"
        assert any("staged" in line for line in complaints)


class TestTheCorpusForcedTwoFixes:
    """Both ruled by the conformance corpus, both red first."""

    def test_a_parent_that_is_a_file_is_a_fault_not_a_fresh_branch(self, tmp_path) -> None:
        """
        Divergence 2. A missing directory on the way to the file means nobody
        has written settings yet; where the OS reads it as missing (Windows), blank is the answer."""
        blocking = tmp_path / "claude-settings"
        blocking.write_text("I am a file, not a directory", encoding="utf-8")
        target = blocking / "settings.local.json"

        with pytest.raises(OSError) as blocked:
            target.read_bytes()
        world_distinguishes_the_fault = not isinstance(blocked.value, FileNotFoundError)

        if world_distinguishes_the_fault:
            with pytest.raises(host_settings.SettingsUnavailable):
                host_settings.read_object(target)
        else:
            assert host_settings.read_object(target) == {}

    def test_a_negative_window_reads_as_null_not_as_a_negative(self, tmp_path) -> None:
        """
        Divergence 5, and the one where rust was already right: their as_u64
        declines a negative outright."""
        view = host_settings.agent_settings_view({"autoCompactWindow": -5})

        assert view["auto_compact_window"] is None

    def test_a_window_of_zero_still_reads_as_zero(self, tmp_path) -> None:
        """
        The boundary the fix must not overshoot. Zero is a representable u64,
        so it reads back; the refusal on zero belongs to the WRITE path."""
        view = host_settings.agent_settings_view({"autoCompactWindow": 0})

        assert view["auto_compact_window"] == 0

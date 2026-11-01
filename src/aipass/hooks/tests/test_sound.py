# =================== AIPass ====================
# Name: test_sound.py
# Version: 2.0.0
# Description: Tests for shared sound module
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-11-01
# =============================================

"""Tests for apps/sound.py."""

# Shared speak/play; silent unless hook sounds are switched on.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — PIPER_BIN and PIPER_VOICE's install locations under the home directory
# seedgo: no-test-needed(documentation) — print_introspection() output, a help screen

import os
import subprocess as real_sub
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from aipass.hooks.apps import sound
from aipass.hooks.apps.sound import is_muted, mute, play, speak, unmute


class TestIsMuted:
    """Hook sounds are off by default: muted unless the sound-on flag exists."""

    def test_a_fresh_home_is_muted(self):
        assert is_muted() is True

    def test_the_sound_flag_turns_sound_on(self):
        sound.SOUND_FLAG.parent.mkdir(parents=True, exist_ok=True)
        sound.SOUND_FLAG.touch()
        assert is_muted() is False


class TestSoundFlagHome:
    """The flag survives a reboot and every TMPDIR: it lives in the user's AIPass home, not the temp dir."""

    def test_the_flag_path_ignores_tmpdir(self, tmp_path):
        """Asked of a fresh child, so the conftest isolation does not answer for the module."""
        probe = "from aipass.hooks.apps import sound; print(sound.SOUND_FLAG)"
        paths = set()
        for tmpdir in (tmp_path / "a", tmp_path / "b"):
            tmpdir.mkdir()
            env = {**os.environ, "TMPDIR": str(tmpdir), "HOME": str(tmp_path / "home")}
            child = real_sub.run(
                [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60
            )
            assert child.returncode == 0, child.stderr
            paths.add(Path(child.stdout.strip()))
        assert paths == {tmp_path / "home" / ".aipass" / "aipass-hooks-sound-on"}

    def test_old_mute_flags_are_removed_once_and_the_seat_stays_muted(self):
        for old in (sound.MUTE_FLAG, sound.LEGACY_MUTE_FLAG):
            old.parent.mkdir(parents=True, exist_ok=True)
            old.touch()
        with patch.object(sound, "logger") as mock_logger:
            assert is_muted() is True
            assert is_muted() is True
        assert not sound.MUTE_FLAG.exists()
        assert not sound.LEGACY_MUTE_FLAG.exists()
        assert mock_logger.info.call_count == 2

    def test_an_old_mute_flag_never_silences_a_seat_that_turned_sound_on(self):
        sound.MUTE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        sound.MUTE_FLAG.touch()
        unmute()
        assert is_muted() is False

    def test_an_old_flag_it_cannot_remove_still_reads_muted(self, monkeypatch):
        """A sandboxed seat cannot write the home: the flag waits for a seat that can, and the answer is muted."""
        locked = MagicMock()
        locked.exists.return_value = True
        locked.unlink.side_effect = PermissionError("read-only home")
        monkeypatch.setattr(sound, "MUTE_FLAG", locked)
        assert is_muted() is True

    def test_the_suite_never_points_at_the_live_flags(self):
        """conftest's isolated_mute_flag: a hooksound test that reached the real home would flip the owner's sound."""
        assert sound.SOUND_FLAG != Path.home() / ".aipass" / "aipass-hooks-sound-on"
        assert sound.MUTE_FLAG != Path.home() / ".aipass" / "aipass-hooks-muted"
        assert sound.LEGACY_MUTE_FLAG != Path(tempfile.gettempdir()) / "aipass-hooks-muted"


class TestSpeak:
    """Piper TTS with mute support."""

    def test_speak_calls_piper_when_not_muted(self, tmp_path):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.PIPER_BIN") as mock_bin,
            patch("aipass.hooks.apps.sound.PIPER_VOICE") as mock_voice,
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            mock_bin.exists.return_value = True
            mock_voice.exists.return_value = True
            mock_sub.run.return_value = MagicMock(returncode=0)

            # The wav is really staged, in the test's own dir through speak's seam (fleet green leg 7).
            speak("test text", tmp_dir=str(tmp_path))

        staged = list(tmp_path.glob("*.wav"))
        assert len(staged) == 1
        wav = str(staged[0])
        mock_sub.run.assert_called_once_with(
            [str(mock_bin), "-m", str(mock_voice), "-f", wav],
            input="test text",
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert mock_sub.Popen.call_count == 1
        (play_cmd,), play_kwargs = mock_sub.Popen.call_args
        assert play_cmd[:2] == ["sh", "-c"] and play_cmd[-1] == wav
        assert play_cmd[2].endswith('; rm -f "$1"'), "the player's shell must remove the wav after playback"
        assert staged[0].exists(), "playback owns the wav once it starts"
        assert play_kwargs == {"stdout": mock_sub.DEVNULL, "stderr": mock_sub.DEVNULL}

    def test_speak_skips_when_muted(self):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=True),
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            speak("test")

        mock_sub.run.assert_not_called()

    def test_speak_skips_when_piper_missing(self):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.PIPER_BIN") as mock_bin,
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            mock_bin.exists.return_value = False
            speak("test")

        mock_sub.run.assert_not_called()

    def test_speak_graceful_on_timeout(self, tmp_path):
        """A piper timeout is caught and named in the log, never raised.

        Had no oracle: "graceful" was asserted by the absence of a traceback, so
        a speak() that never reached piper at all - a guard returning early, a
        patch that stopped biting - passed exactly the same. The log line is
        what proves the except leg is the one that ran.
        """
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.PIPER_BIN") as mock_bin,
            patch("aipass.hooks.apps.sound.PIPER_VOICE") as mock_voice,
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
            patch("aipass.hooks.apps.sound.logger") as mock_logger,
        ):
            mock_bin.exists.return_value = True
            mock_voice.exists.return_value = True
            mock_sub.run.side_effect = real_sub.TimeoutExpired("piper", 5)
            mock_sub.TimeoutExpired = real_sub.TimeoutExpired

            speak("test", tmp_dir=str(tmp_path))

        assert mock_sub.run.call_count == 1
        mock_logger.info.assert_called_once_with("[HOOKS] speak: piper timed out")
        assert not list(tmp_path.glob("*.wav")), "a timed-out synthesis leaves no wav behind"

    def test_a_failed_synthesis_leaves_no_wav(self, tmp_path):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.PIPER_BIN") as mock_bin,
            patch("aipass.hooks.apps.sound.PIPER_VOICE") as mock_voice,
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            mock_bin.exists.return_value = True
            mock_voice.exists.return_value = True
            mock_sub.run.return_value = MagicMock(returncode=1)

            speak("test", tmp_dir=str(tmp_path))

        mock_sub.Popen.assert_not_called()
        assert not list(tmp_path.glob("*.wav"))

    def test_speak_graceful_on_os_error(self, tmp_path):
        """A missing piper binary is caught and the reason carried into the log."""
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.PIPER_BIN") as mock_bin,
            patch("aipass.hooks.apps.sound.PIPER_VOICE") as mock_voice,
            patch("aipass.hooks.apps.sound.subprocess.run", side_effect=OSError("broken")),
            patch("aipass.hooks.apps.sound.logger") as mock_logger,
        ):
            mock_bin.exists.return_value = True
            mock_voice.exists.return_value = True

            speak("test", tmp_dir=str(tmp_path))

        assert mock_logger.info.call_count == 1
        template, exc = mock_logger.info.call_args[0]
        assert template == "[HOOKS] speak: playback error: %s"
        assert str(exc) == "broken"


class TestPlay:
    """WAV playback with mute support."""

    def test_play_calls_aplay_when_not_muted(self):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True

            play(mock_path)

        assert mock_sub.Popen.call_count == 1
        (play_cmd,), play_kwargs = mock_sub.Popen.call_args
        assert play_cmd[-1] == str(mock_path)
        assert play_kwargs == {"stdout": mock_sub.DEVNULL, "stderr": mock_sub.DEVNULL}

    def test_play_skips_when_muted(self, tmp_path):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=True),
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            play(tmp_path / "sound.wav")

        mock_sub.Popen.assert_not_called()

    def test_play_skips_when_file_missing(self):
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.subprocess") as mock_sub,
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = False

            play(mock_path)

        mock_sub.Popen.assert_not_called()

    def test_play_graceful_on_os_error(self):
        """A missing player is caught and the reason carried into the log.

        Had no oracle. Note the file-not-found leg logs a DIFFERENT line, so
        pinning the template is what separates "the player is missing" from
        "the sound file is missing" - two failures with one silent outcome.
        """
        with (
            patch("aipass.hooks.apps.sound.is_muted", return_value=False),
            patch("aipass.hooks.apps.sound.subprocess.Popen", side_effect=OSError("no player")),
            patch("aipass.hooks.apps.sound.logger") as mock_logger,
        ):
            mock_path = MagicMock()
            mock_path.exists.return_value = True

            play(mock_path)

        assert mock_logger.info.call_count == 1
        template, exc = mock_logger.info.call_args[0]
        assert template == "[HOOKS] play: playback error: %s"
        assert str(exc) == "no player"


class TestMuteWritePair:
    """The write half of the door — exported so callers stop shelling out (@api ask)."""

    def test_unmute_creates_the_sound_flag_on_a_fresh_home_and_is_idempotent(self):
        assert not sound.SOUND_FLAG.parent.exists()
        assert unmute() is False
        assert unmute() is False
        assert sound.SOUND_FLAG.exists()

    def test_mute_removes_the_sound_flag(self):
        unmute()
        assert mute() is True
        assert not sound.SOUND_FLAG.exists()

    def test_mute_is_idempotent_on_a_missing_flag(self):
        assert mute() is True
        assert mute() is True
        assert not sound.SOUND_FLAG.exists()

    def test_round_trip_agrees_with_is_muted(self):
        """@api flips then reads back through is_muted() — the two halves must agree."""
        assert unmute() == is_muted() is False
        assert mute() == is_muted() is True

    def test_writes_are_logged(self):
        """A state change nobody can audit left no trace before — hooksound imported
        the logger and never called it."""
        with patch.object(sound, "logger") as mock_logger:
            sound.unmute()
            sound.mute()
        assert [c.args[0] for c in mock_logger.info.call_args_list] == [
            "[HOOKS] sound: unmuted",
            "[HOOKS] sound: muted",
        ]

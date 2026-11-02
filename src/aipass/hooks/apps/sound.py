# =================== AIPass ====================
# Name: sound.py
# Version: 2.0.0
# Description: Shared sound utilities — Piper TTS and WAV playback with mute support
# Branch: hooks
# Layer: apps
# Created: 2026-05-22
# Modified: 2026-11-01
# =============================================

"""Shared sound functions for hook handlers. Silent unless hook sounds are switched on."""

import subprocess
import sys
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import err_console

CONSOLE = err_console
# Sound is the exception: off unless this flag exists. Per-user, outside the temp dir so a reboot keeps it.
SOUND_FLAG = Path.home() / ".aipass" / "aipass-hooks-sound-on"
# The mute flags of the sound-on-by-default era; is_muted() removes either on sight.
MUTE_FLAG = Path.home() / ".aipass" / "aipass-hooks-muted"
LEGACY_MUTE_FLAG = Path(tempfile.gettempdir()) / "aipass-hooks-muted"
PIPER_BIN = Path.home() / ".local" / "share" / "piper" / "piper"
PIPER_VOICE = Path.home() / ".local" / "share" / "piper-voices" / "en_US-amy-medium.onnx"

if sys.platform == "darwin":
    _PLAY_CMD: list[str] = ["afplay"]
else:
    _PLAY_CMD = ["aplay", "-q"]


def print_introspection():
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]sound[/bold cyan] — Shared sound utilities (speak, play, mute)")


def is_muted() -> bool:
    """True unless SOUND_FLAG exists: hook sounds are off by default. An old mute flag is redundant and is removed."""
    for old in (MUTE_FLAG, LEGACY_MUTE_FLAG):
        if old.exists():
            try:
                old.unlink(missing_ok=True)
            except OSError as exc:
                # A sandboxed seat cannot write the home; it is muted either way, an unsandboxed seat removes it.
                logger.info("[HOOKS] sound: old mute flag %s left in place: %s", old, exc)
                continue
            logger.info("[HOOKS] sound: removed old mute flag %s (muted is the default now)", old)
    return not SOUND_FLAG.exists()


def mute() -> bool:
    """Turn hook sounds off. Idempotent.

    Returns the resulting muted state (always True); @api imports this directly.
    """
    SOUND_FLAG.unlink(missing_ok=True)
    logger.info("[HOOKS] sound: muted")
    return True


def unmute() -> bool:
    """Turn hook sounds on. Idempotent."""
    SOUND_FLAG.parent.mkdir(parents=True, exist_ok=True)
    SOUND_FLAG.touch()
    logger.info("[HOOKS] sound: unmuted")
    return False


def speak(text: str, tmp_dir: str | None = None) -> None:
    """Generate speech via Piper TTS and play it. Skips if muted.

    tmp_dir is a test seam: tests pass their own dir instead of patching tempfile process-wide.
    """
    if is_muted():
        return

    if not PIPER_BIN.exists() or not PIPER_VOICE.exists():
        return

    wav_path, playing = "", False
    try:
        wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=tmp_dir)
        wav_path = wav_file.name
        wav_file.close()

        piper_result = subprocess.run(
            [str(PIPER_BIN), "-m", str(PIPER_VOICE), "-f", wav_path],
            input=text,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if piper_result.returncode == 0 and Path(wav_path).exists():
            # The player's own shell removes the wav when playback ends: the prompt path never waits on it.
            subprocess.Popen(
                ["sh", "-c", " ".join(_PLAY_CMD) + ' "$1"; rm -f "$1"', "sh", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            playing = True
    except subprocess.TimeoutExpired:
        logger.info("[HOOKS] speak: piper timed out")
    except OSError as exc:
        logger.info("[HOOKS] speak: playback error: %s", exc)
    finally:
        if wav_path and not playing:
            Path(wav_path).unlink(missing_ok=True)


def play(sound_path: Path) -> None:
    """Play a WAV file. Skips if muted."""
    if is_muted():
        return

    if not sound_path.exists():
        logger.info("[HOOKS] play: file not found: %s", sound_path)
        return

    try:
        subprocess.Popen(
            _PLAY_CMD + [str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.info("[HOOKS] play: playback error: %s", exc)

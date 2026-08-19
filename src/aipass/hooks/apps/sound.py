# =================== AIPass ====================
# Name: sound.py
# Version: 1.1.0
# Description: Shared sound utilities — Piper TTS and WAV playback with mute support
# Branch: hooks
# Layer: apps
# Created: 2026-05-22
# Modified: 2026-08-18
# =============================================

"""Shared sound functions for hook handlers. Checks mute flag before playing."""

import subprocess
import sys
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import err_console

CONSOLE = err_console
MUTE_FLAG = Path(tempfile.gettempdir()) / "aipass-hooks-muted"
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
    """Check whether hook sounds are currently muted."""
    return MUTE_FLAG.exists()


def mute() -> bool:
    """Mute all hook sounds. Idempotent.

    Returns:
        The resulting muted state — always True, so a caller can flip and
        verify in one call instead of writing then reading back.

    Note:
        Exported so callers stop shelling out to `drone @hooks hooksound off`
        just to flip a flag (@api asked; their words were "I would rather that
        than shell out"). This module owns MUTE_FLAG, so the write belongs
        beside the read that already lived here.
    """
    MUTE_FLAG.touch()
    logger.info("[HOOKS] sound: muted")
    return True


def unmute() -> bool:
    """Unmute all hook sounds. Idempotent — a missing flag is already unmuted.

    Returns:
        The resulting muted state — always False, mirroring mute().
    """
    MUTE_FLAG.unlink(missing_ok=True)
    logger.info("[HOOKS] sound: unmuted")
    return False


def speak(text: str) -> None:
    """Generate speech via Piper TTS and play it. Skips if muted."""
    if is_muted():
        return

    if not PIPER_BIN.exists() or not PIPER_VOICE.exists():
        return

    try:
        wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
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
            subprocess.Popen(
                _PLAY_CMD + [wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except subprocess.TimeoutExpired:
        logger.info("[HOOKS] speak: piper timed out")
    except OSError as exc:
        logger.info("[HOOKS] speak: playback error: %s", exc)


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

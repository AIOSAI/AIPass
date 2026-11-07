# =================== AIPass ====================
# Name: speech.py
# Description: Host API Speech — read a line aloud: Piper streams raw PCM for the client to play as it arrives
# Version: 1.0.0
# Created: 2026-11-05
# Modified: 2026-11-05
# =============================================

"""
Host API Speech
Reference: docs/host_agent_chat.md. Ported from Seed Dev's deck (ui/speech.py). Piper (the install @hooks' sound
uses) streams raw 16-bit mono PCM, sentence by sentence: the first sentence plays while the rest is still being made,
and a multi-line text stays one stream. Linux installs only; elsewhere Piper is simply not found.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Generator

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

PIPER_BIN = Path(".local") / "share" / "piper" / "piper"
PIPER_VOICE = Path(".local") / "share" / "piper-voices" / "en_US-amy-medium.onnx"
CHUNK_BYTES = 4096


class SpeechUnavailable(Exception):
    """Piper, its voice, or the voice's sample rate is missing; the words are for the host log only."""


def piper_bin() -> Path:
    """The Piper binary under the user's home."""
    return Path.home() / PIPER_BIN


def piper_voice() -> Path:
    """The voice model under the user's home; its config sits beside it as <voice>.onnx.json."""
    return Path.home() / PIPER_VOICE


def sample_rate() -> int:
    """The voice's sample rate, from the config Piper ships beside the model; SpeechUnavailable when unread."""
    binary, voice = piper_bin(), piper_voice()
    if not binary.is_file() or not voice.is_file():
        raise SpeechUnavailable(f"Piper is not installed at {binary} with the voice {voice.name}")
    config = voice.with_suffix(".onnx.json")
    try:
        return int(json.loads(config.read_text(encoding="utf-8"))["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("[host_api] unreadable voice config %s: %s", config, exc)
        raise SpeechUnavailable(f"Piper's voice config {config.name} has no sample rate") from exc


def stream(text: str) -> Generator[bytes, None, None]:
    """Raw PCM chunks of *text* as Piper makes them; closing the generator kills Piper (the client hung up)."""
    proc = subprocess.Popen(
        [str(piper_bin()), "-m", str(piper_voice()), "--output_raw", "-q"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    json_handler.log_operation("host_api_speak", {"chars": len(text)})
    try:
        if proc.stdin is None or proc.stdout is None:
            raise SpeechUnavailable("Piper started without its pipes")
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        while chunk := os.read(proc.stdout.fileno(), CHUNK_BYTES):  # whatever is ready, not a full buffer
            yield chunk
    finally:
        if proc.poll() is None:
            logger.info("[host_api] speech stopped before Piper finished")
            proc.kill()
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()
